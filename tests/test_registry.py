import os
from pathlib import Path

import pytest

from tuojing_model_platform_service.config import Settings
from tuojing_model_platform_service.registry import (
    CopyPermissionError,
    InvalidSourceError,
    ModelRegistry,
    VersionConflictError,
)
from tuojing_model_platform_service.schemas import QueryRequest, ReleaseRequest


@pytest.fixture
def registry(tmp_path: Path) -> tuple[ModelRegistry, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(
        meta_dir=tmp_path / "meta",
        release_dir=tmp_path / "release",
    )
    return ModelRegistry(settings), workspace


def create_model(workspace: Path, name: str, content: str = "weights") -> Path:
    source = workspace / name
    source.mkdir(exist_ok=True)
    (source / "model.pt").write_text(content, encoding="utf-8")
    (source / "config.json").write_text('{"format":"test"}', encoding="utf-8")
    return source


def test_release_versions_and_query_history(
    registry: tuple[ModelRegistry, Path],
) -> None:
    service, workspace = registry
    source = create_model(workspace, "umi-policy")

    first = service.release(
        ReleaseRequest(
            project_name="Umi2Isaac",
            model_name="umi-policy",
            source_path=str(source),
            released_by="alice",
        )
    )
    assert first.version == "0.0.1"
    assert first.model_uri.endswith("/Umi2Isaac/umi-policy/0.0.1/")
    assert first.released_by == "alice"
    assert first.released_at is not None
    assert first.released_at.endswith("Z")

    (source / "model.pt").write_text("new-weights", encoding="utf-8")
    second = service.release(
        ReleaseRequest(
            project_name="Umi2Isaac",
            model_name="umi-policy",
            source_path=str(source),
            version_strategy="minor",
        )
    )
    assert second.version == "0.1.0"
    assert second.sha256 != first.sha256

    latest = service.query(QueryRequest(project_name="Umi2Isaac"))
    assert [model.version for model in latest] == ["0.1.0"]

    all_versions = service.query(
        QueryRequest(project_name="Umi2Isaac", latest_only=False)
    )
    assert {model.version for model in all_versions} == {"0.0.1", "0.1.0"}


def test_exact_version_conflict_and_force_replace(
    registry: tuple[ModelRegistry, Path],
) -> None:
    service, workspace = registry
    source = create_model(workspace, "umi-policy")
    request = ReleaseRequest(
        project_name="Umi2Isaac",
        model_name="umi-policy",
        source_path=str(source),
        version_strategy="exact",
        version="2.0.0",
    )
    original = service.release(request)

    with pytest.raises(VersionConflictError):
        service.release(request)

    (source / "model.pt").write_text("replacement", encoding="utf-8")
    replaced = service.release(request.model_copy(update={"force_replace": True}))
    assert replaced.version == "2.0.0"
    assert replaced.sha256 != original.sha256


def test_source_can_be_anywhere_but_must_match_model_name(
    registry: tuple[ModelRegistry, Path], tmp_path: Path
) -> None:
    service, workspace = registry
    wrong_name = create_model(workspace, "another-name")
    with pytest.raises(InvalidSourceError):
        service.release(
            ReleaseRequest(
                project_name="Umi2Isaac",
                model_name="umi-policy",
                source_path=str(wrong_name),
            )
        )

    outside = tmp_path / "outside" / "umi-policy"
    outside.mkdir(parents=True)
    (outside / "model.pt").write_text("weights", encoding="utf-8")
    released = service.release(
        ReleaseRequest(
            project_name="Umi2Isaac",
            model_name="umi-policy",
            source_path=str(outside),
        )
    )
    assert released.version == "0.0.1"


def test_source_dereferences_symlinks(registry: tuple[ModelRegistry, Path]) -> None:
    service, workspace = registry
    source = create_model(workspace, "umi-policy")
    shared = workspace / "shared"
    shared.mkdir()
    (shared / "shared.pt").write_text("shared-weights", encoding="utf-8")
    linked = source / "linked.pt"
    linked.symlink_to(shared / "shared.pt")

    released = service.release(
        ReleaseRequest(
            project_name="Umi2Isaac",
            model_name="umi-policy",
            source_path=str(source),
        )
    )

    published_link = Path(released.model_uri) / "linked.pt"
    assert published_link.read_text(encoding="utf-8") == "shared-weights"
    assert not published_link.is_symlink()


def test_source_dereferences_symlink_to_any_readable_path(
    registry: tuple[ModelRegistry, Path], tmp_path: Path
) -> None:
    service, workspace = registry
    source = create_model(workspace, "umi-policy")
    outside = tmp_path / "outside-model.pt"
    outside.write_text("outside", encoding="utf-8")
    (source / "outside.pt").symlink_to(outside)

    released = service.release(
        ReleaseRequest(
            project_name="Umi2Isaac",
            model_name="umi-policy",
            source_path=str(source),
        )
    )
    published = Path(released.model_uri) / "outside.pt"
    assert published.read_text(encoding="utf-8") == "outside"
    assert not published.is_symlink()


def test_source_requires_absolute_existing_path(
    registry: tuple[ModelRegistry, Path],
) -> None:
    service, workspace = registry

    with pytest.raises(InvalidSourceError, match="absolute path"):
        service.release(
            ReleaseRequest(
                project_name="Umi2Isaac",
                model_name="umi-policy",
                source_path="relative/umi-policy",
            )
        )

    with pytest.raises(InvalidSourceError, match="does not exist"):
        service.release(
            ReleaseRequest(
                project_name="Umi2Isaac",
                model_name="umi-policy",
                source_path=str(workspace / "missing-model"),
            )
        )


def test_source_permission_error_provides_repair_command(
    registry: tuple[ModelRegistry, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    service, workspace = registry
    source = create_model(workspace, "umi-policy")
    original_access = os.access

    def deny_source(path: os.PathLike[str] | str, mode: int) -> bool:
        if Path(path) == source and mode == os.R_OK | os.X_OK:
            return False
        return original_access(path, mode)

    monkeypatch.setattr(os, "access", deny_source)

    with pytest.raises(CopyPermissionError) as raised:
        service.release(
            ReleaseRequest(
                project_name="Umi2Isaac",
                model_name="umi-policy",
                source_path=str(source),
            )
        )

    assert "setfacl" in raised.value.suggested_command
    assert str(source) in raised.value.suggested_command
