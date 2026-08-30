from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_META_DIR = Path("/data/model-registry/model_meta")
DEFAULT_RELEASE_DIR = Path("/data/model-registry/model_release")
DEFAULT_WORKSPACE_ROOT = Path("/data/workspace")


@dataclass(frozen=True)
class Settings:
    meta_dir: Path = DEFAULT_META_DIR
    release_dir: Path = DEFAULT_RELEASE_DIR
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            meta_dir=Path(
                os.environ.get("MODEL_PLATFORM_META_DIR", str(DEFAULT_META_DIR))
            ),
            release_dir=Path(
                os.environ.get("MODEL_PLATFORM_RELEASE_DIR", str(DEFAULT_RELEASE_DIR))
            ),
            workspace_root=Path(
                os.environ.get(
                    "MODEL_PLATFORM_WORKSPACE_ROOT", str(DEFAULT_WORKSPACE_ROOT)
                )
            ),
        )

