from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _resolve_frontend_dir() -> Path:
    candidates = [
        BACKEND_DIR / "frontend",
        PROJECT_ROOT / "frontend",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return PROJECT_ROOT / "frontend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/swimtimer.db"
    RESET_PASSWORD: str = "maratona2025"
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    FRONTEND_DIR: str = ""

    @property
    def frontend_dir(self) -> Path:
        if self.FRONTEND_DIR:
            return Path(self.FRONTEND_DIR)
        return _resolve_frontend_dir()


settings = Settings()
