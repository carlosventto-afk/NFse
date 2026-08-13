from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_url_test: str = ""
    fernet_key: str
    jwt_secret: str
    jwt_ttl_horas: int = 8
    smtp_host: str = "smtp.hostinger.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    app_base_url: str = "https://nfse.gestaotecnologia.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
