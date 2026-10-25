"""Settings from the environment (TRD §10). `.env.example` lists every variable."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo-root .env, so `uv run` from api/ and `docker compose` read the same file.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("/data")
    database_url: str = "sqlite:////data/sherlock.db"

    llm_base_url: str = ""
    llm_api_key: str = ""
    model_large: str = ""
    model_medium: str = ""
    model_small: str = ""
    model_embed: str = ""
    nvidia_embed_models: str = ""
    llm_tools_mode: Literal["json", "native"] = "json"
    # Answer model calls from recorded fixtures (a JSON file or a directory of them) instead of Token Factory.
    llm_mock: str = ""
    # Append every live model reply to this fixture file (to record fixtures from a real run).
    llm_record: str = ""

    job_backend: Literal["local", "nebius"] = "local"
    job_workers: int = 4
    sandbox_cpu_s: int = 30
    sandbox_mem_mb: int = 2048
    # Unix socket of sherlock-sandboxd (the image sets it); empty: workers start directly (dev, tests).
    sandboxd_socket: str = ""
    # Where workers' temp directories go, outside DATA_DIR; empty: <system temp>/sherlock-sandbox.
    sandbox_tmp: str = ""

    # Memory cap of each DuckDB connection (ingest and the per-version query cache).
    duckdb_memory_mb: int = 1024

    max_upload_mb: int = 50
    max_columns: int = 1000
    max_rows: int = 2_000_000
    user_storage_mb: int = 500
    dataset_ttl_days: int = 7

    user_token_budget: int = 2_000_000
    job_token_budget: int = 300_000
    message_token_budget: int = 40_000
    # Every user's model calls together, per UTC day (0 = no ceiling): the cap on spend that a client
    # dropping its cookie can't reset (TRD §15).
    app_token_budget: int = 10_000_000
    new_users_per_ip_hour: int = 30  # 0 = no cap
    # X-Forwarded-For entries the host's own proxies append after the client's (Render: 1, checked live).
    trusted_proxy_hops: int = 1

    clean_max_steps: int = 20
    clean_max_seconds: int = 300

    tavily_api_key: str = ""
    notebook_pins: str = (
        "pandas==2.2.3,duckdb==1.1.3,numpy==2.1.3,scikit-learn==1.5.2,"
        "statsmodels==0.14.4,matplotlib==3.9.2,rapidfuzz==3.10.1,"
        "dateparser==1.2.0,ftfy==6.3.1"
    )
    cors_origins: str = ""
    log_level: str = "info"
    # The built web app, served under / from the API origin (TRD §11). Empty in local dev (Vite serves it).
    web_dist_dir: Path | None = None

    @property
    def models(self) -> dict[str, str]:
        """The four model roles (TRD §3.5), as reported by /healthz."""
        return {
            "large": self.model_large,
            "medium": self.model_medium,
            "small": self.model_small,
            "embed": self.model_embed,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
