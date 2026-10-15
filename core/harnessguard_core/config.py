"""Central configuration, read from environment (SPEC section 11)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"  # local|cloud

    database_url: str = "postgresql+psycopg://hg:hg@db:5432/harnessguard"
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


def get_settings() -> Settings:
    return Settings()
