from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseRequest(StrictModel):
    project_name: str = Field(min_length=1, max_length=128)
    model_name: str = Field(min_length=1, max_length=128)
    source_path: str = Field(min_length=1)
    version_strategy: Literal["patch", "minor", "major", "exact"] = "patch"
    version: str | None = None
    force_replace: bool = False
    released_by: str | None = Field(default=None, max_length=128)

    @field_validator("released_by")
    @classmethod
    def normalize_released_by(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_release(self) -> "ReleaseRequest":
        for label, value in (
            ("project_name", self.project_name),
            ("model_name", self.model_name),
        ):
            if not NAME_PATTERN.fullmatch(value):
                raise ValueError(
                    f"{label} must match {NAME_PATTERN.pattern!r}"
                )

        if self.version_strategy == "exact":
            if self.version is None:
                raise ValueError("version is required when version_strategy is exact")
            if not VERSION_PATTERN.fullmatch(self.version):
                raise ValueError("version must use MAJOR.MINOR.PATCH")
        elif self.version is not None:
            raise ValueError("version is only allowed when version_strategy is exact")
        return self


class QueryRequest(StrictModel):
    project_name: str | None = Field(default=None, max_length=128)
    model_name: str | None = Field(default=None, max_length=128)
    version: str | None = None
    latest_only: bool = True

    @model_validator(mode="after")
    def validate_query(self) -> "QueryRequest":
        for label, value in (
            ("project_name", self.project_name),
            ("model_name", self.model_name),
        ):
            if value is not None and not NAME_PATTERN.fullmatch(value):
                raise ValueError(
                    f"{label} must match {NAME_PATTERN.pattern!r}"
                )
        if self.version is not None and not VERSION_PATTERN.fullmatch(self.version):
            raise ValueError("version must use MAJOR.MINOR.PATCH")
        return self


class ModelMetadata(StrictModel):
    project_name: str
    model_name: str
    version: str
    model_uri: str
    sha256: str
    released_by: str | None = None
    released_at: str | None = None


class ReleaseResponse(StrictModel):
    model: ModelMetadata


class QueryResponse(StrictModel):
    models: list[ModelMetadata]
