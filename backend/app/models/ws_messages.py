from pydantic import BaseModel
from typing import Optional


class HealthResponse(BaseModel):
    hermes_installed: bool
    hermes_version: Optional[str] = None
    configured: bool = False
    current_model: Optional[str] = None
    current_provider: Optional[str] = None


class ProviderInfo(BaseModel):
    id: str
    name: str
    description: str
    requires_key: bool
    configured: bool = False
    icon: str = ""


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str
    context_length: Optional[int] = None


class ConfigureProviderRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class SelectModelRequest(BaseModel):
    model_id: str
    provider: Optional[str] = None


class TestConnectionResponse(BaseModel):
    success: bool
    response: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
