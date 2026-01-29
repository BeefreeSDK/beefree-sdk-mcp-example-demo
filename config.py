import uuid

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""

    # Beefree SDK Configuration
    beefree_client_id: str = Field(description="Beefree SDK Client ID")
    beefree_client_secret: str = Field(description="Beefree SDK Client Secret")
    beefree_uid: str = Field(
        default_factory=lambda: f"user_{uuid.uuid4().hex[:8]}",
        description="Unique user identifier for Beefree SDK",
    )
    beefree_mcp_api_key: str = Field(description="api key for mcp service")

    ai_provider: str = Field(description="Model provider: gemini or openai")
    llm_model: str = Field(description="Model to use")
    gemini_api_key: str | None = Field(default=None, description="Gemini api key")
    openai_api_key: str | None = Field(default=None, description="OpenAI api key")

    app_host: str = Field(default="0.0.0.0", description="Host to bind to")
    app_port: int = Field(default=8000, description="Port to bind to")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


try:
    settings = Settings()
except ValidationError as exc:
    missing = {err["loc"][0] for err in exc.errors()}
    if "ai_provider" in missing:
        raise SystemExit("Missing required env var: AI_PROVIDER (gemini or openai)") from exc
    if "llm_model" in missing:
        raise SystemExit("Missing required env var: LLM_MODEL") from exc
    raise
