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
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    FRONTEND_DIR: str = ""
    LOGO_DIR: str = ""
    THEME_DIR: str = ""
    MAX_LOGO_BYTES: int = 1_048_576
    MAX_THEME_IMAGE_BYTES: int = 2_097_152
    MAX_THEME_IMAGE_PX: int = 3840
    MAX_IMPORT_BYTES: int = 2_097_152
    MAX_IMPORT_ROWS: int = 1000
    MIN_LAP_INTERVAL_S: float = 5.0
    LATE_AFTER_S: float = 2.0
    # PIN do supervisor para autorizar excecoes de inscricao (force).
    # Se nao configurado, nenhum override e aceito.
    OPERATOR_PIN: str | None = None
    # Diario NDJSON por evento (auditoria externa, append-only).
    JOURNAL_DIR: str = ""
    # Backup continuo: intervalo entre backups e destino espelho opcional
    # (pendrive). O espelho precisa estar visivel dentro do container.
    BACKUP_INTERVAL_MIN: float = 5.0
    BACKUP_MIRROR_DIR: str = ""
    BACKUP_DIR: str = ""

    @property
    def journal_dir(self) -> Path:
        if self.JOURNAL_DIR:
            return Path(self.JOURNAL_DIR)
        return BACKEND_DIR / "data" / "journal"

    @property
    def backup_dir(self) -> Path:
        if self.BACKUP_DIR:
            return Path(self.BACKUP_DIR)
        return BACKEND_DIR / "data" / "backups"

    @property
    def frontend_dir(self) -> Path:
        if self.FRONTEND_DIR:
            return Path(self.FRONTEND_DIR)
        return _resolve_frontend_dir()

    @property
    def logo_dir(self) -> Path:
        if self.LOGO_DIR:
            return Path(self.LOGO_DIR)
        return BACKEND_DIR / "data" / "logos"

    @property
    def theme_dir(self) -> Path:
        if self.THEME_DIR:
            return Path(self.THEME_DIR)
        return BACKEND_DIR / "data" / "theme"


settings = Settings()
