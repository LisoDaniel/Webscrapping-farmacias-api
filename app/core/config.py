from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "WebScrapping Farmácias API"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Scraping
    SCRAPER_TIMEOUT_SECONDS: float = 15.0
    SCRAPER_MAX_CONCURRENCY: int = 5
    SCRAPER_RETRY_ATTEMPTS: int = 2

    # Banco de dados. O padrão corresponde ao PostgreSQL do docker-compose.
    DATABASE_URL: str = (
        "postgresql+asyncpg://webscrapping:webscrapping_local@"
        "localhost:5432/webscrapping_farmacias"
    )
    DATABASE_ECHO: bool = False

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    CLIENTS_DIR: Path = BASE_DIR / "Clientes"
    REPORTS_DIR: Path = BASE_DIR / "reports"

    # Coleta assistida: payloads capturados no navegador para as redes que
    # bloqueiam cliente automatizado. Ver tools/captura_panvel.js.
    CAPTURES_DIR: Path = BASE_DIR / "capturas"
    # Preço envelhece. Passado esse prazo a captura é ignorada em vez de virar
    # um valor desatualizado apresentado como atual.
    CAPTURE_MAX_AGE_HOURS: float = 24.0

    # HTTP Client headers
    DEFAULT_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
# Garante a existência da pasta reports
settings.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
