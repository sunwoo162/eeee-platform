from pathlib import Path
import os
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.paths import default_data_dir


def _user_data_root() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return (Path(root) if root else Path.home() / ".local" / "share") / "Gleave"


class Settings(BaseSettings):
    app_name: str = "Gleave"
    data_dir: Path = Field(
        default_factory=default_data_dir,
        validation_alias=AliasChoices("EEEE_DATA_DIR", "DATA_DIR"),
    )
    workspace_root: Path = Field(
        default_factory=lambda: default_data_dir() / "workspaces",
        validation_alias=AliasChoices("EEEE_WORKSPACE_ROOT", "WORKSPACE_ROOT"),
    )
    github_token: str | None = None
    notion_token: str | None = None
    notion_parent_page_id: str | None = None
    notion_api_base: str = "https://api.notion.com"
    notion_api_version: str = "2026-03-11"
    plugin_provider_config_json: str | None = None
    gmail_oauth_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EEEE_GMAIL_OAUTH_CLIENT_ID", "GMAIL_OAUTH_CLIENT_ID"),
    )
    gmail_oauth_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EEEE_GMAIL_OAUTH_CLIENT_SECRET", "GMAIL_OAUTH_CLIENT_SECRET"),
    )
    iseol_bridge_token: str | None = None
    claim_latch_adapter_url: str | None = None
    claim_latch_auto_start: bool = True
    claim_latch_adapter_port: int = 4318
    claimlatch_llm_model: str | None = None
    claimlatch_llm_api_key: str | None = None
    claimlatch_llm_base_url: str | None = None
    tavily_api_key: str | None = None
    claim_latch_policy_version: str = "claimlatch-policy-v1"
    claim_latch_adapter_version: str = "eeee-claimlatch-adapter-v1"
    claim_latch_profile_version: str = "claimlatch-v0.2.0"
    claim_latch_version: str = "0.3.86"
    claim_latch_mode: Literal["advisory", "required"] = "advisory"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    chatgpt_web_enabled: bool = False
    chatgpt_web_bridge_url: str | None = None
    chatgpt_web_autostart: bool = False
    chatgpt_web_profile_root: Path | None = None
    chatgpt_web_browser_executable: str | None = None
    # The Web session is an implementation detail. Only the explicit login
    # action opens Chrome; normal assistant requests use a background browser.
    chatgpt_web_headless: bool = True
    chatgpt_web_bridge_port: int = 47831
    chatgpt_web_node_path: str = "node"
    chatgpt_web_timeout_seconds: float = 120.0
    # The bridge allows one initial agent turn plus up to two strict-parser
    # corrections, each bounded at 45 seconds. Keep the Python request open
    # long enough to receive the final bounded attempt.
    chatgpt_web_agent_timeout_seconds: float = 150.0
    assistant_profile_path: Path = Field(default_factory=lambda: _user_data_root() / "profile.json")
    local_model_base_url: str = "http://127.0.0.1:11434/api/chat"
    local_model: str | None = None
    local_conversation_model: str | None = None
    local_model_timeout_seconds: float = 120.0
    conversation_provider: Literal["auto", "personal_llm", "chatgpt_web", "ollama"] = Field(
        default="personal_llm",
        validation_alias=AliasChoices("EEEE_CONVERSATION_PROVIDER", "CONVERSATION_PROVIDER"),
    )
    personal_llm_base_url: str = Field(
        default="http://127.0.0.1:8765",
        validation_alias=AliasChoices("EEEE_PERSONAL_LLM_BASE_URL", "PERSONAL_LLM_BASE_URL"),
    )
    personal_llm_connect_timeout_seconds: float = Field(
        default=3.0,
        validation_alias=AliasChoices(
            "EEEE_PERSONAL_LLM_CONNECT_TIMEOUT_SECONDS",
            "PERSONAL_LLM_CONNECT_TIMEOUT_SECONDS",
        ),
    )
    personal_llm_generation_timeout_seconds: float = Field(
        default=120.0,
        validation_alias=AliasChoices(
            "EEEE_PERSONAL_LLM_GENERATION_TIMEOUT_SECONDS",
            "PERSONAL_LLM_GENERATION_TIMEOUT_SECONDS",
        ),
    )
    personal_llm_autostart: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "EEEE_PERSONAL_LLM_AUTOSTART",
            "PERSONAL_LLM_AUTOSTART",
        ),
    )
    personal_llm_project_root: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "EEEE_PERSONAL_LLM_PROJECT_ROOT",
            "PERSONAL_LLM_PROJECT_ROOT",
        ),
    )
    personal_llm_executable: str = Field(
        default="personal-llm",
        validation_alias=AliasChoices(
            "EEEE_PERSONAL_LLM_EXECUTABLE",
            "PERSONAL_LLM_EXECUTABLE",
        ),
    )
    personal_llm_startup_timeout_seconds: float = Field(
        default=45.0,
        validation_alias=AliasChoices(
            "EEEE_PERSONAL_LLM_STARTUP_TIMEOUT_SECONDS",
            "PERSONAL_LLM_STARTUP_TIMEOUT_SECONDS",
        ),
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        validation_alias=AliasChoices("EEEE_OLLAMA_BASE_URL", "OLLAMA_BASE_URL"),
    )
    ollama_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EEEE_OLLAMA_MODEL", "OLLAMA_MODEL"),
    )
    ollama_connect_timeout_seconds: float = Field(
        default=3.0,
        validation_alias=AliasChoices(
            "EEEE_OLLAMA_CONNECT_TIMEOUT_SECONDS", "OLLAMA_CONNECT_TIMEOUT_SECONDS"
        ),
    )
    ollama_generation_timeout_seconds: float = Field(
        default=120.0,
        validation_alias=AliasChoices(
            "EEEE_OLLAMA_GENERATION_TIMEOUT_SECONDS", "OLLAMA_GENERATION_TIMEOUT_SECONDS"
        ),
    )
    ollama_context_tokens: int = Field(
        default=8192,
        validation_alias=AliasChoices("EEEE_OLLAMA_CONTEXT_TOKENS", "OLLAMA_CONTEXT_TOKENS"),
    )
    agent_runtime: Literal["chatgpt_web", "openhands"] = "chatgpt_web"
    iseol_bridge_script: Path = Path("packages/iseol/scripts/eeee-chatgpt-web-bridge.ts")
    iseol_node_executable: str = "node"
    iseol_control_plane_url: str | None = None
    iseol_control_plane_token: str | None = None
    project_auto_execute: bool = False
    execution_mode: Literal["demo", "workspace_verify"] = "demo"
    mobile_bridge_enabled: bool = True
    mobile_pairing_ttl_seconds: int = 600
    command_timeout_seconds: float = 120.0
    max_command_output_chars: int = 8_000

    @field_validator("command_timeout_seconds")
    @classmethod
    def validate_command_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        return value

    @field_validator("max_command_output_chars")
    @classmethod
    def validate_max_command_output_chars(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_command_output_chars must be positive")
        return value

    @field_validator("mobile_pairing_ttl_seconds")
    @classmethod
    def validate_mobile_pairing_ttl(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("mobile_pairing_ttl_seconds must be positive")
        return value

    @field_validator("local_model_timeout_seconds")
    @classmethod
    def validate_local_model_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("local_model_timeout_seconds must be positive")
        return value

    @field_validator("chatgpt_web_timeout_seconds")
    @classmethod
    def validate_chatgpt_web_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("chatgpt_web_timeout_seconds must be positive")
        return value

    @field_validator("chatgpt_web_agent_timeout_seconds")
    @classmethod
    def validate_chatgpt_web_agent_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("chatgpt_web_agent_timeout_seconds must be positive")
        return value

    @field_validator("chatgpt_web_bridge_port")
    @classmethod
    def validate_chatgpt_web_port(cls, value: int) -> int:
        if value < 1024 or value > 65535:
            raise ValueError("chatgpt_web_bridge_port must be between 1024 and 65535")
        return value

    @field_validator("ollama_connect_timeout_seconds", "ollama_generation_timeout_seconds")
    @classmethod
    def validate_ollama_timeouts(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Ollama timeouts must be positive")
        return value

    @field_validator(
        "personal_llm_connect_timeout_seconds",
        "personal_llm_generation_timeout_seconds",
    )
    @classmethod
    def validate_personal_llm_timeouts(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Personal LLM timeouts must be positive")
        return value

    @field_validator("personal_llm_startup_timeout_seconds")
    @classmethod
    def validate_personal_llm_startup_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Personal LLM startup timeout must be positive")
        return value

    @field_validator("personal_llm_project_root", mode="before")
    @classmethod
    def normalize_personal_llm_project_root(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ollama_context_tokens")
    @classmethod
    def validate_ollama_context_tokens(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("ollama_context_tokens must be positive")
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
