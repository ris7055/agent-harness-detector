"""Central configuration, read from environment (SPEC section 11)."""

from __future__ import annotations

from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"  # local|cloud

    database_url: str = "postgresql+psycopg://hg:hg@db:5432/harnessguard"

    # Cloud SQL (Cloud Run): when these are set and database_url is left at its
    # default, the Postgres unix-socket URL is built from them (see below).
    db_user: str = ""
    db_pass: str = ""
    db_name: str = ""
    instance_connection_name: str = ""  # project:region:instance
    session_secret: str = "change-me"
    console_password: str = "change-me"

    scorer_url: str = "http://scorer:8081"
    event_transport: str = "http"  # http|pubsub

    gcp_project: str = ""
    gcp_region: str = "asia-southeast1"
    pubsub_topic: str = "session-events"
    bq_dataset: str = "harness_detector"
    analytics_sink: str = "jsonl"  # jsonl|bigquery

    model_uri: str = ""  # empty -> rules
    benchmark_uri: str = "./data/benchmark.json"

    llm_mode: str = "mock"  # mock|apikey|vertex
    gemini_model: str = "gemini-2.5-flash"
    gemini_api_key: str = ""

    allow_below: float = 0.50
    block_above: float = 0.85

    allow_data_collection: bool = True
    ip_hash_salt: str = "change-me"
    internal_token: str = "change-me"
    pubsub_push_token: str = "change-me"

    # Demo/testing override: allow|step_up|block (empty = use scorer). D1 stub only.
    force_decision: str = ""

    _DEFAULT_DB_URL = "postgresql+psycopg://hg:hg@db:5432/harnessguard"

    @model_validator(mode="after")
    def _build_cloudsql_url(self) -> "Settings":
        """On Cloud Run, build the Cloud SQL unix-socket URL from the DB_* vars
        when DATABASE_URL was not set explicitly. The password stays in Secret
        Manager (passed as DB_PASS); it is never baked into an image or a URL
        in the deploy command."""
        if (self.instance_connection_name and self.db_user and self.db_name
                and self.database_url == self._DEFAULT_DB_URL):
            socket = f"/cloudsql/{self.instance_connection_name}"
            self.database_url = (
                f"postgresql+psycopg://{quote(self.db_user)}:"
                f"{quote(self.db_pass)}@/{self.db_name}?host={socket}"
            )
        return self


def get_settings() -> Settings:
    return Settings()
