import uuid

from pydantic import Field
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

    llm_model: str = Field(default="gpt-5-mini", description="Model to use")
    openai_api_key: str = Field(description="Openai api key")

    app_host: str = Field(default="0.0.0.0", description="Host to bind to")
    app_port: int = Field(default=8000, description="Port to bind to")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
