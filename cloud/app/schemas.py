from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    device_name: str = Field(default="ZeroCode device", min_length=1, max_length=120)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=256)


class ProviderCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    base_url: str = Field(min_length=12, max_length=500)
    api_key: SecretStr | None = None
    is_enabled: bool = True


class ProviderPatch(BaseModel):
    base_url: str | None = Field(default=None, min_length=12, max_length=500)
    api_key: SecretStr | None = None
    is_enabled: bool | None = None


class ModelCreate(BaseModel):
    provider_id: str
    alias: str = Field(min_length=2, max_length=120, pattern=r"^[a-zA-Z0-9._:-]+$")
    model_name: str = Field(min_length=1, max_length=200)
    task_types: list[str] = Field(default_factory=list, max_length=12)
    priority: int = Field(default=100, ge=1, le=10000)
    supports_tools: bool = True
    supports_vision: bool = False

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, values: list[str]) -> list[str]:
        allowed = {"coding", "architecture", "security", "sysadmin", "vision", "fast"}
        if any(value not in allowed for value in values):
            raise ValueError("Unsupported task type")
        return list(dict.fromkeys(values))


class ModelPatch(BaseModel):
    task_types: list[str] | None = None
    priority: int | None = Field(default=None, ge=1, le=10000)
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    is_enabled: bool | None = None

    @field_validator("task_types")
    @classmethod
    def validate_optional_task_types(cls, values: list[str] | None) -> list[str] | None:
        allowed = {"coding", "architecture", "security", "sysadmin", "vision", "fast"}
        if values is not None and any(value not in allowed for value in values):
            raise ValueError("Unsupported task type")
        return list(dict.fromkeys(values)) if values is not None else None


class RoutingPolicyIn(BaseModel):
    model_aliases: list[str] = Field(min_length=1, max_length=20)


class ClientConfigPatch(BaseModel):
    maintenance_mode: bool | None = None
    client_min_version: str | None = Field(default=None, max_length=30)
    feature_flags: dict[str, bool] | None = None


class GuardrailsPatch(BaseModel):
    requests_per_minute: int | None = Field(default=None, ge=1, le=120)
    max_concurrent_requests: int | None = Field(default=None, ge=1, le=20)
    max_prompt_chars: int | None = Field(default=None, ge=1000, le=500000)
    max_output_tokens: int | None = Field(default=None, ge=256, le=32768)
    max_messages: int | None = Field(default=None, ge=1, le=200)


class UserStatusPatch(BaseModel):
    is_active: bool


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = Field(default="auto", min_length=1, max_length=120)
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    stream: bool = False
    temperature: float | None = Field(default=0.2, ge=0, le=2)
    max_tokens: int | None = Field(default=8192, ge=1, le=32768)

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not all(item.get("role") in {"system", "user", "assistant", "tool"} for item in values):
            raise ValueError("Unsupported message role")
        return values

    def upstream_payload(self, upstream_model: str) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True)
        payload["model"] = upstream_model
        for key, value in (self.model_extra or {}).items():
            if key not in {"user", "metadata", "max_completion_tokens", "n"}:
                payload[key] = value
        return payload
