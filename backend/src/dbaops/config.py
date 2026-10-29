import re
from functools import lru_cache

from claude_agent_sdk import McpServerConfig
from pydantic import BaseModel, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InstanceProfile(BaseModel):
    """How dbatools reaches a configuration item. Only instances listed here can be worked on."""

    # SqlInstance for SQL-level commands, e.g. "localhost" or "10.70.1.5,1433"
    sql_instance: str
    # ComputerName for Windows-level commands (remoting, services, disks, installs); no port
    computer_name: str | None = None
    # dbatools credential parameter -> MCP-host credential profile alias, e.g. {"SqlCredential": "windowstest-reader"}
    credential_refs: dict[str, str] = {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    anthropic_foundry_resource: str | None = None
    anthropic_foundry_base_url: str | None = None
    anthropic_foundry_api_key: SecretStr
    claude_model: str = "claude-sonnet-5-5"

    dbatools_mcp_url: str | None = None
    dbatools_mcp_token: SecretStr | None = None
    dbatools_mcp_command: str | None = None
    dbatools_mcp_args: str = ""
    # CA bundle for a self-signed MCP server certificate; passed to the Claude CLI (Node).
    node_extra_ca_certs: str | None = None

    # JSON: {"<configuration item>": {"sql_instance": "...", "computer_name": "...", "credential_refs": {...}}}
    dbaops_instances: dict[str, InstanceProfile] = {}

    dbaops_api_token: SecretStr
    dbaops_db_path: str = "dbaops.db"
    itsm_base_url: str
    itsm_token: SecretStr | None = None

    dbaops_max_turns: int = 40
    dbaops_subagent_max_turns: int = 25
    # Agent working time; the clock pauses while waiting for a human approval.
    dbaops_run_timeout_seconds: float = 900
    dbaops_approval_timeout_seconds: float = 3600

    @model_validator(mode="after")
    def _require_endpoints(self) -> "Settings":
        if not (self.anthropic_foundry_resource or self.anthropic_foundry_base_url):
            raise ValueError("Set ANTHROPIC_FOUNDRY_RESOURCE or ANTHROPIC_FOUNDRY_BASE_URL")
        if self.anthropic_foundry_resource and not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?", self.anthropic_foundry_resource
        ):
            raise ValueError(
                "ANTHROPIC_FOUNDRY_RESOURCE must be the resource name only (e.g. my-resource from "
                "https://my-resource.services.ai.azure.com), not a URL. Use ANTHROPIC_FOUNDRY_BASE_URL for a full URL."
            )
        if not (self.dbatools_mcp_url or self.dbatools_mcp_command):
            raise ValueError("Set DBATOOLS_MCP_URL (HTTPS) or DBATOOLS_MCP_COMMAND (stdio)")
        return self

    def instance_for(self, configuration_item: str) -> InstanceProfile | None:
        wanted = configuration_item.lower()
        return next((p for ci, p in self.dbaops_instances.items() if ci.lower() == wanted), None)

    def cli_env(self) -> dict[str, str]:
        env = {
            "CLAUDE_CODE_USE_FOUNDRY": "1",
            "ANTHROPIC_FOUNDRY_API_KEY": self.anthropic_foundry_api_key.get_secret_value(),
            # Subagents must return their report as the Agent tool result, not as a later background notification.
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
        }
        if self.anthropic_foundry_resource:
            env["ANTHROPIC_FOUNDRY_RESOURCE"] = self.anthropic_foundry_resource
        if self.anthropic_foundry_base_url:
            env["ANTHROPIC_FOUNDRY_BASE_URL"] = self.anthropic_foundry_base_url
        if self.node_extra_ca_certs:
            env["NODE_EXTRA_CA_CERTS"] = self.node_extra_ca_certs
        return env

    def mcp_servers(self) -> dict[str, McpServerConfig]:
        if self.dbatools_mcp_url:
            headers = {}
            if self.dbatools_mcp_token:
                headers["Authorization"] = f"Bearer {self.dbatools_mcp_token.get_secret_value()}"
            return {"dbatools": {"type": "http", "url": self.dbatools_mcp_url, "headers": headers}}
        assert self.dbatools_mcp_command
        return {
            "dbatools": {
                "type": "stdio",
                "command": self.dbatools_mcp_command,
                "args": self.dbatools_mcp_args.split(),
                "env": {"DBATOOLS_SAFE_MODE": "true"},
            }
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
