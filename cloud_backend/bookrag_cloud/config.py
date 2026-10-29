from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "bookrag-pdfs"
    voyage_api_key: str = ""
    openai_api_key: str = ""
    allowed_origins: str = "http://localhost:3000"
    max_pdf_bytes: int = 25 * 1024 * 1024
    max_pdf_pages: int = 2000
    max_passages: int = 3000
    daily_upload_limit: int = 5
    daily_question_limit: int = 50
    questions_per_minute_limit: int = 10
    daily_estimated_usd_limit: float = 5.0
    question_reserve_usd: float = 0.05
    worker_poll_seconds: float = 2.0

    def origins(self) -> list[str]:
        return [x.strip() for x in self.allowed_origins.split(",") if x.strip()]


@lru_cache
def settings() -> Settings:
    return Settings()
