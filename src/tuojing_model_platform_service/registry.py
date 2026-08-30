from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import shlex
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import Settings
from .schemas import ModelMetadata, QueryRequest, ReleaseRequest


class RegistryError(Exception):
    """Base error returned by the registry."""


class InvalidSourceError(RegistryError):
    """The supplied source directory violates the workspace contract."""


class CopyPermissionError(InvalidSourceError):
    """The service process cannot read and copy the supplied model directory."""

    def __init__(self, message: str, suggested_command: str):
        super().__init__(message)
        self.suggested_command = suggested_command


class VersionConflictError(RegistryError):
    """The requested model version already exists."""


class MetadataError(RegistryError):
    """The metadata store is invalid or unavailable."""


class ModelRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.meta_dir.mkdir(parents=True, exist_ok=True)
        self.settings.release_dir.mkdir(parents=True, exist_ok=True)
        self.latest_path = self.settings.meta_dir / "model_meta.json"
        self.record_path = self.settings.meta_dir / "model_meta_record.json"
        self.lock_path = self.settings.meta_dir / ".model-registry.lock"
        self._initialize_metadata()

    def release(self, request: ReleaseRequest) -> ModelMetadata:
        source = self._validate_source(request.source_path, request.model_name)

        with self._lock(exclusive=True):
            latest_document = self._read_latest()
            record_document = self._read_record()
            key = self._model_key(request.project_name, request.model_name)
            previous = latest_document["models"].get(key)
            version = self._target_version(request, previous)
            target = (
                self.settings.release_dir
                / request.project_name
                / request.model_name
                / version
            )

            if target.exists() and not request.force_replace:
                raise VersionConflictError(
                    f"model version already exists: {request.project_name}/"
                    f"{request.model_name}/{version}"
                )

            target.parent.mkdir(parents=True, exist_ok=True)
            staging = target.parent / f".{version}.staging-{uuid.uuid4().hex}"
            backup: Path | None = None
            published = False

            try:
                try:
                    shutil.copytree(source, staging, symlinks=False)
                except PermissionError as error:
                    raise self._copy_permission_error(source, error) from error
                except shutil.Error as error:
                    if "Permission denied" in str(error):
                        raise self._copy_permission_error(source) from error
                    raise
                digest = self._directory_sha256(staging)

                if target.exists():
                    backup = target.parent / f".{version}.backup-{uuid.uuid4().hex}"
                    os.replace(target, backup)
                os.replace(staging, target)
                published = True

                metadata = ModelMetadata(
                    project_name=request.project_name,
                    model_name=request.model_name,
                    version=version,
                    model_uri=f"{target.resolve()}/",
                    sha256=digest,
                    released_by=request.released_by,
                    released_at=(
                        datetime.now(timezone.utc)
                        .isoformat(timespec="seconds")
                        .replace("+00:00", "Z")
                    ),
                )

                if previous is not None:
                    record_document["records"].append(previous)
                latest_document["models"][key] = metadata.model_dump()

                self._atomic_write_json(self.record_path, record_document)
                self._atomic_write_json(self.latest_path, latest_document)

                if backup is not None:
                    shutil.rmtree(backup)
                return metadata
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging)
                if published and target.exists():
                    shutil.rmtree(target)
                if backup is not None and backup.exists():
                    os.replace(backup, target)
                raise

    def query(self, request: QueryRequest) -> list[ModelMetadata]:
        with self._lock(exclusive=False):
            latest = list(self._read_latest()["models"].values())
            records = [] if request.latest_only else self._read_record()["records"]

        results: list[ModelMetadata] = []
        for raw in [*latest, *records]:
            metadata = ModelMetadata.model_validate(raw)
            if request.project_name and metadata.project_name != request.project_name:
                continue
            if request.model_name and metadata.model_name != request.model_name:
                continue
            if request.version and metadata.version != request.version:
                continue
            results.append(metadata)

        return sorted(
            results,
            key=lambda item: (
                item.project_name,
                item.model_name,
                self._parse_version(item.version),
            ),
            reverse=True,
        )

    def _validate_source(self, source_path: str, model_name: str) -> Path:
        raw_source = Path(source_path)
        if not raw_source.is_absolute():
            raise InvalidSourceError("source_path must be an absolute path")

        try:
            workspace = self.settings.workspace_root.resolve(strict=True)
        except FileNotFoundError as error:
            raise InvalidSourceError(
                f"configured workspace root does not exist: {self.settings.workspace_root}"
            ) from error
        except PermissionError as error:
            raise self._copy_permission_error(raw_source, error) from error

        try:
            source = raw_source.resolve(strict=True)
        except FileNotFoundError as error:
            raise InvalidSourceError(f"source_path does not exist: {raw_source}") from error
        except PermissionError as error:
            raise self._copy_permission_error(raw_source, error) from error

        if not source.is_dir():
            raise InvalidSourceError("source_path must be a directory")
        if not source.is_relative_to(workspace) or source == workspace:
            raise InvalidSourceError(
                f"source_path must be below workspace root: {workspace}"
            )
        if raw_source.name != model_name:
            raise InvalidSourceError(
                f"source directory name must equal model_name: {model_name}"
            )

        has_file = self._assert_copy_permissions(source, workspace)
        if not has_file:
            raise InvalidSourceError("source directory must contain at least one file")
        return source

    def _assert_copy_permissions(self, source: Path, workspace: Path) -> bool:
        has_file = False
        active_directories: set[Path] = set()

        def resolve_link(path: Path) -> Path:
            try:
                target = path.resolve(strict=True)
            except FileNotFoundError as error:
                raise InvalidSourceError(
                    f"symbolic link target does not exist: {path}"
                ) from error
            except PermissionError as error:
                raise self._copy_permission_error(path, error) from error
            if not target.is_relative_to(workspace):
                raise InvalidSourceError(
                    f"symbolic link target must stay below workspace root: {path} -> "
                    f"{target}"
                )
            return target

        def visit(directory: Path) -> None:
            nonlocal has_file
            resolved_directory = resolve_link(directory) if directory.is_symlink() else directory
            resolved_directory = resolved_directory.resolve(strict=True)

            if resolved_directory in active_directories:
                raise InvalidSourceError(
                    f"cyclic symbolic link is not allowed: {directory}"
                )
            if not os.access(resolved_directory, os.R_OK | os.X_OK):
                raise self._copy_permission_error(resolved_directory)

            active_directories.add(resolved_directory)
            try:
                with os.scandir(resolved_directory) as entries:
                    for entry in entries:
                        path = Path(entry.path)
                        if entry.is_symlink():
                            target = resolve_link(path)
                            if target.is_dir():
                                visit(path)
                            elif target.is_file():
                                if not os.access(target, os.R_OK):
                                    raise self._copy_permission_error(target)
                                has_file = True
                            else:
                                raise InvalidSourceError(
                                    f"symbolic link target must be a regular file or directory: "
                                    f"{path}"
                                )
                        elif entry.is_dir(follow_symlinks=False):
                            visit(path)
                        elif entry.is_file(follow_symlinks=False):
                            if not os.access(path, os.R_OK):
                                raise self._copy_permission_error(path)
                            has_file = True
                        else:
                            raise InvalidSourceError(
                                f"source contains an unsupported file type: {path}"
                            )
            except PermissionError as error:
                raise self._copy_permission_error(resolved_directory, error) from error
            finally:
                active_directories.remove(resolved_directory)

        visit(source)
        return has_file

    def _copy_permission_error(
        self, source: Path, error: PermissionError | None = None
    ) -> CopyPermissionError:
        service_user = pwd.getpwuid(os.geteuid()).pw_name
        workspace = Path(os.path.abspath(self.settings.workspace_root))
        source = Path(os.path.abspath(source))

        ancestors: list[Path] = [workspace]
        if source.is_relative_to(workspace):
            relative_parent = source.parent.relative_to(workspace)
            current = workspace
            for part in relative_parent.parts:
                current /= part
                ancestors.append(current)

        traverse_paths = " ".join(shlex.quote(str(path)) for path in ancestors)
        suggested_command = (
            f"sudo setfacl -m u:{service_user}:x -- {traverse_paths} && "
            f"sudo setfacl -R -m u:{service_user}:rX -- {shlex.quote(str(source))}"
        )
        detail = f"service user {service_user!r} cannot read model source: {source}"
        if error is not None and error.filename:
            detail += f" ({error.filename})"
        return CopyPermissionError(detail, suggested_command)

    def _target_version(
        self, request: ReleaseRequest, previous: dict[str, str] | None
    ) -> str:
        if request.version_strategy == "exact":
            assert request.version is not None
            return request.version

        if previous is None:
            return "0.0.1"

        major, minor, patch = self._parse_version(previous["version"])
        if request.version_strategy == "major":
            return f"{major + 1}.0.0"
        if request.version_strategy == "minor":
            return f"{major}.{minor + 1}.0"
        return f"{major}.{minor}.{patch + 1}"

    @staticmethod
    def _parse_version(version: str) -> tuple[int, int, int]:
        try:
            major, minor, patch = version.split(".")
            return int(major), int(minor), int(patch)
        except (TypeError, ValueError) as error:
            raise MetadataError(f"invalid stored model version: {version!r}") from error

    @staticmethod
    def _model_key(project_name: str, model_name: str) -> str:
        return f"{project_name}/{model_name}"

    @staticmethod
    def _directory_sha256(directory: Path) -> str:
        digest = hashlib.sha256()
        files = sorted(path for path in directory.rglob("*") if path.is_file())
        for path in files:
            relative = path.relative_to(directory).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()

    def _initialize_metadata(self) -> None:
        with self._lock(exclusive=True):
            if not self.latest_path.exists():
                self._atomic_write_json(
                    self.latest_path,
                    {"schema_version": "model-meta.v1", "models": {}},
                )
            if not self.record_path.exists():
                self._atomic_write_json(
                    self.record_path,
                    {"schema_version": "model-meta-record.v1", "records": []},
                )

    def _read_latest(self) -> dict:
        document = self._read_json(self.latest_path)
        if document.get("schema_version") != "model-meta.v1" or not isinstance(
            document.get("models"), dict
        ):
            raise MetadataError(f"invalid latest metadata file: {self.latest_path}")
        return document

    def _read_record(self) -> dict:
        document = self._read_json(self.record_path)
        if document.get("schema_version") != "model-meta-record.v1" or not isinstance(
            document.get("records"), list
        ):
            raise MetadataError(f"invalid metadata record file: {self.record_path}")
        return document

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            with path.open("r", encoding="utf-8") as stream:
                document = json.load(stream)
        except (OSError, json.JSONDecodeError) as error:
            raise MetadataError(f"cannot read metadata file: {path}") from error
        if not isinstance(document, dict):
            raise MetadataError(f"metadata root must be an object: {path}")
        return document

    @staticmethod
    def _atomic_write_json(path: Path, document: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @contextmanager
    def _lock(self, *, exclusive: bool) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as stream:
            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(stream.fileno(), mode)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
