from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    itsm_db_path: str = "itsm.db"
    itsm_api_token: SecretStr
    dbaops_api_url: str = "http://localhost:8000"
    dbaops_api_token: SecretStr


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
