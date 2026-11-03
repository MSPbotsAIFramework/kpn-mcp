"""Service configuration.

Only non-credential settings live here. KPN client credentials arrive per
request via HTTP headers (see server.py) and must never be read from
environment variables or configuration files (SOP section 3.1).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Non-credential runtime settings.

    `extra="ignore"` is required: the deployment environment injects
    variables this project does not declare, and an unknown variable must
    never crash startup (SOP section 1.2).
    """

    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080

    kpn_base_url: str = "https://api-prd.kpn.com"
    kpn_token_url: str = "https://api-prd.kpn.com/oauth/client_credential/accesstoken"


settings = Settings()
