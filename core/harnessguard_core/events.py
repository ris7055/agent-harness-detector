"""Pydantic models for telemetry event batches (SPEC section 5.3).

Privacy rules (AGENTS.md): payloads carry timings, key classes and value
lengths only -- never key values, input values or passwords.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

EventType = Literal[
    "fingerprint",
    "page",
    "mousemove",
    "click",
    "keydown",
    "keyup",
    "input",
    "paste",
    "focus",
    "blur",
    "scroll",
    "visibility",
    "submit",
]


class Event(BaseModel):
    seq: int
    t: float  # performance.now() ms since page load
    wall: int  # Date.now() epoch ms
    type: EventType
    page: str
    data: dict[str, Any] = Field(default_factory=dict)


class EventBatch(BaseModel):
    session_id: UUID
    page_load_id: UUID
    sent_at: int  # epoch ms
    events: list[Event] = Field(default_factory=list)
