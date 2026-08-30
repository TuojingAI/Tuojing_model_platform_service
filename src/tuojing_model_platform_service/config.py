from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_META_DIR = Path("/data/model_registry/model_meta")
DEFAULT_RELEASE_DIR = Path("/data/model_registry/model_release")


@dataclass(frozen=True)
class Settings:
    meta_dir: Path = DEFAULT_META_DIR
    release_dir: Path = DEFAULT_RELEASE_DIR

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            meta_dir=Path(
                os.environ.get("MODEL_PLATFORM_META_DIR", str(DEFAULT_META_DIR))
            ),
            release_dir=Path(
                os.environ.get("MODEL_PLATFORM_RELEASE_DIR", str(DEFAULT_RELEASE_DIR))
            ),
        )
