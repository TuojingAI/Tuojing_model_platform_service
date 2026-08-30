from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from tuojing_model_platform_service.api import create_app
from tuojing_model_platform_service.config import Settings
from tuojing_model_platform_service.registry import CopyPermissionError


def test_release_query_and_health(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "umi-policy"
    source.mkdir(parents=True)
    (source / "model.pt").write_bytes(b"weights")

    app = create_app(
        Settings(
            meta_dir=tmp_path / "custom-meta",
            release_dir=tmp_path / "release",
        )
    )
    client = TestClient(app)

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["meta_dir"] == str(tmp_path / "custom-meta")
    assert "workspace_root" not in health.json()

    released = client.post(
        "/api/v1/models/release",
        json={
            "project_name": "Umi2Isaac",
            "model_name": "umi-policy",
            "source_path": str(source),
            "released_by": "alice",
        },
    )
    assert released.status_code == 200
    assert released.json()["model"]["version"] == "0.0.1"
    assert released.json()["model"]["released_by"] == "alice"
    assert released.json()["model"]["released_at"].endswith("Z")

    queried = client.post(
        "/api/v1/models/query",
        json={"project_name": "Umi2Isaac", "latest_only": True},
    )
    assert queried.status_code == 200
    assert len(queried.json()["models"]) == 1


def test_api_accepts_source_from_any_absolute_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "umi-policy"
    outside.mkdir(parents=True)
    (outside / "model.pt").write_bytes(b"weights")

    client = TestClient(
        create_app(
            Settings(
                meta_dir=tmp_path / "meta",
                release_dir=tmp_path / "release",
            )
        )
    )
    response = client.post(
        "/api/v1/models/release",
        json={
            "project_name": "Umi2Isaac",
            "model_name": "umi-policy",
            "source_path": str(outside),
        },
    )
    assert response.status_code == 200


def test_api_returns_permission_repair_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        Settings(
            meta_dir=tmp_path / "meta",
            release_dir=tmp_path / "release",
        )
    )

    def reject_release(_payload: object) -> None:
        raise CopyPermissionError(
            "service user cannot read model source",
            "sudo setfacl -R -m u:model-service:rX -- /data/workspace/model",
        )

    monkeypatch.setattr(app.state.registry, "release", reject_release)
    response = TestClient(app).post(
        "/api/v1/models/release",
        json={
            "project_name": "Umi2Isaac",
            "model_name": "umi-policy",
            "source_path": "/data/workspace/umi-policy",
        },
    )

    assert response.status_code == 403
    assert "setfacl" in response.json()["suggested_command"]
