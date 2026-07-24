"""Preset adapters for well-known parser engines."""

from __future__ import annotations

from dataclasses import dataclass

from ..schema.common import MediaCategory
from ..schema.engine import EngineBackendConfig, ParserEngine
from ..schema.hardware import DeviceRuntime
from ..schema.remote import RemoteBackendConfig
from .remote import RemoteHttpBackend


@dataclass(frozen=True, slots=True)
class EngineCapabilityPreset:
    media_categories: tuple[MediaCategory, ...]
    mime_types: tuple[str, ...] = ()


ENGINE_CAPABILITY_PRESETS: dict[ParserEngine, EngineCapabilityPreset] = {
    ParserEngine.PADDLEOCR: EngineCapabilityPreset(
        media_categories=(MediaCategory.IMAGE, MediaCategory.DOCUMENT),
        mime_types=("image/*", "application/pdf"),
    ),
    ParserEngine.PADDLEOCR_VL: EngineCapabilityPreset(
        media_categories=(MediaCategory.IMAGE, MediaCategory.DOCUMENT),
        mime_types=("image/*", "application/pdf"),
    ),
    ParserEngine.HUNYUAN_OCR: EngineCapabilityPreset(
        media_categories=(MediaCategory.IMAGE, MediaCategory.DOCUMENT),
        mime_types=("image/*", "application/pdf"),
    ),
    ParserEngine.MINERU: EngineCapabilityPreset(
        media_categories=(MediaCategory.DOCUMENT,),
        mime_types=(
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ),
    ParserEngine.ASR: EngineCapabilityPreset(
        media_categories=(MediaCategory.AUDIO,),
        mime_types=("audio/*",),
    ),
    ParserEngine.VLM: EngineCapabilityPreset(
        media_categories=(MediaCategory.IMAGE,),
        mime_types=("image/*",),
    ),
    ParserEngine.VIDEO_VLM: EngineCapabilityPreset(
        media_categories=(MediaCategory.VIDEO,),
        mime_types=("video/*",),
    ),
    ParserEngine.WEB_RENDERED: EngineCapabilityPreset(
        media_categories=(MediaCategory.WEB,),
        mime_types=("text/html", "application/xhtml+xml"),
    ),
}


def engine_remote_config(config: EngineBackendConfig) -> RemoteBackendConfig:
    preset = ENGINE_CAPABILITY_PRESETS[config.engine]
    return RemoteBackendConfig(
        name=config.engine.value,
        version=config.version,
        endpoint=config.endpoint,
        authentication=config.authentication,
        media_categories=list(preset.media_categories),
        mime_types=list(preset.mime_types),
        maximum_concurrency=config.maximum_concurrency,
        timeout_seconds=config.timeout_seconds,
        maximum_response_bytes=config.maximum_response_bytes,
        maximum_artifacts=config.maximum_artifacts,
        maximum_artifact_bytes=config.maximum_artifact_bytes,
    )


class EngineRemoteBackend(RemoteHttpBackend):
    """Remote Backend 1.0 adapter with a canonical engine capability preset."""

    def __init__(
        self,
        *,
        config: EngineBackendConfig,
        runtime: DeviceRuntime,
        transport: object | None = None,
    ) -> None:
        self.engine_config = config
        super().__init__(
            config=engine_remote_config(config),
            runtime=runtime,
            transport=transport,
        )


__all__ = [
    "ENGINE_CAPABILITY_PRESETS",
    "EngineCapabilityPreset",
    "EngineRemoteBackend",
    "engine_remote_config",
]
