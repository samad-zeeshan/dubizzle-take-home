"""
Settings for the whole service, read once from the environment and .env.

Every flag the transparency layer reports lives here, so /health and each
turn trace can show the configuration the answer was produced under.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DUBAI = ZoneInfo("Asia/Dubai")

ABLATION_FLAGS = (
    "ablate_sanitizer",
    "ablate_prefilter",
    "ablate_postfilter",
    "ablate_grounding_check",
    "ablate_relaxation",
    "ablate_resolver",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    gemini_api_key: str | None = None
    llm_provider: Literal["litellm", "mock"] = "litellm"
    llm_model: str = "gemini/gemini-2.5-flash-lite"
    llm_fallback_model: str | None = "gemini/gemini-2.5-flash"
    llm_temperature: float | None = None
    llm_reasoning: str = "low"
    llm_cassette_mode: Literal["off", "record", "replay"] = "off"
    llm_cassette_path: Path = Path("data/cassettes/demo.jsonl")
    verify_mode: Literal["off", "llm"] = "off"
    structured_reply: bool = True
    summary_after_turns: int = 12
    idempotency_ttl_seconds: int = 600
    debug_endpoints: bool = False
    retrieval_mode: Literal["structured", "fts", "hybrid", "embeddings"] = "hybrid"
    embedding_model: str = "gemini/gemini-embedding-001"
    demo_now: datetime | None = None

    rate_limit_per_min: int = 20
    rate_limit_per_day: int = 300
    daily_llm_budget: int = 1000
    max_message_chars: int = 1000
    max_tool_iterations: int = 4
    history_turns: int = 10
    session_idle_minutes: int = 30

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    backend_url: str = "http://127.0.0.1:8000"
    data_dir: Path = ROOT / "data"
    logs_dir: Path = ROOT / "logs"
    outbox_dir: Path = ROOT / "outbox"
    # Overrides so tests and demos can point state files elsewhere while sharing the inventory.
    db_file: Path | None = None
    inventory_file: Path | None = None
    embeddings_file: Path | None = None
    leads_file: Path | None = None
    bookings_file: Path | None = None
    log_level: str = "INFO"

    ablate_sanitizer: bool = False
    ablate_prefilter: bool = False
    ablate_postfilter: bool = False
    ablate_grounding_check: bool = False
    ablate_relaxation: bool = False
    ablate_resolver: bool = False

    @field_validator(
        "llm_cassette_path",
        "data_dir",
        "logs_dir",
        "outbox_dir",
        "db_file",
        "inventory_file",
        "embeddings_file",
        "leads_file",
        "bookings_file",
        mode="after",
    )
    @classmethod
    def _absolute(cls, v: Path | None) -> Path | None:
        # Relative paths in .env are relative to the repo, never to whatever cwd uvicorn was started from.
        if v is None:
            return None
        return v if v.is_absolute() else ROOT / v

    @field_validator("demo_now", mode="after")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=DUBAI)
        return v

    @property
    def db_path(self) -> Path:
        return self.db_file or self.data_dir / "app.db"

    @property
    def inventory_path(self) -> Path:
        return self.inventory_file or self.data_dir / "inventory.json"

    @property
    def embeddings_path(self) -> Path:
        return self.embeddings_file or self.data_dir / "embeddings.npy"

    @property
    def leads_csv(self) -> Path:
        return self.leads_file or self.data_dir / "leads.csv"

    @property
    def bookings_csv(self) -> Path:
        return self.bookings_file or self.data_dir / "bookings.csv"

    @property
    def ablations_active(self) -> list[str]:
        return [f.removeprefix("ablate_") for f in ABLATION_FLAGS if getattr(self, f)]

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider == "mock" or bool(self.gemini_api_key)

    def now(self) -> datetime:
        """Dubai wall clock, or the frozen demo clock when one is set."""
        if self.demo_now is not None:
            return self.demo_now.astimezone(DUBAI)
        return datetime.now(DUBAI)

    def temperature_for(self, model: str) -> float | None:
        # Google warns against low temperature on Gemini 3; 2.5 is happy with it.
        if self.llm_temperature is not None:
            return self.llm_temperature
        return 0.2 if "2.5" in model or "2.0" in model else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
