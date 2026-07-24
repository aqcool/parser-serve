"""Optional Ray Serve integration for model-service deployments."""

from .gateway import (
    RayInferenceHandler,
    RayServeDeploymentConfig,
    RemoteProtocolGateway,
    build_ray_serve_application,
)

__all__ = [
    "RayInferenceHandler",
    "RayServeDeploymentConfig",
    "RemoteProtocolGateway",
    "build_ray_serve_application",
]
