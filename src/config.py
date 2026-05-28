"""Configuración central del proyecto (cargada desde .env)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Credenciales Growatt OSS
    growatt_user: str = ""
    growatt_password: str = ""

    # Base de datos
    database_url: str = "sqlite:///growatt_test.db"

    # API
    api_key: str = "PRUEBAS_GROWATT_INVERSORES"
    api_host: str = "127.0.0.1"
    api_port: int = 8001

    # Scraper / Playwright
    headless: bool = True
    nav_timeout_ms: int = 60000

    # Constantes del portal Growatt
    oss_base: str = "https://oss.growatt.com"
    server_base: str = "https://server.growatt.com"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
