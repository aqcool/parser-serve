"""Named parser engine access configuration."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AnyHttpUrl, Field, model_validator

from .base import StrictSchema
from .common import NonEmptyStr
from .remote import RemoteBackendAuthentication


class ParserEngine(StrEnum):
    PADDLEOCR = "paddleocr"
    PADDLEOCR_VL = "paddleocr_vl"
    HUNYUAN_OCR = "hunyuan_ocr"
    MINERU = "mineru"
    ASR = "asr"
    VLM = "vlm"
    VIDEO_VLM = "video_vlm"
    WEB_RENDERED = "web_rendered"


class EngineBackendConfig(StrictSchema):
    engine: ParserEngine
    version: NonEmptyStr = "1.0"
    endpoint: AnyHttpUrl
    authentication: RemoteBackendAuthentication = Field(
        default_factory=RemoteBackendAuthentication
    )
    maximum_concurrency: Annotated[int, Field(ge=1, le=1000, strict=True)] = 1
    timeout_seconds: Annotated[float, Field(gt=0.0, le=86_400.0, strict=True)] = 600.0
    maximum_response_bytes: Annotated[
        int,
        Field(ge=1, le=1024 * 1024 * 1024, strict=True),
    ] = 64 * 1024 * 1024
    maximum_artifacts: Annotated[int, Field(ge=0, le=1000, strict=True)] = 100
    maximum_artifact_bytes: Annotated[
        int,
        Field(ge=1, le=1024 * 1024 * 1024, strict=True),
    ] = 32 * 1024 * 1024

    @model_validator(mode="after")
    def validate_endpoint(self) -> EngineBackendConfig:
        if (
            self.endpoint.username is not None
            or self.endpoint.password is not None
            or self.endpoint.fragment is not None
        ):
            raise ValueError(
                "engine Backend endpoint cannot contain credentials or a fragment"
            )
        return self


__all__ = ["EngineBackendConfig", "ParserEngine"]
