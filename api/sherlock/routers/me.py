"""Identity and settings (TRD §4.1): GET /me, PUT /me/settings."""

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from sherlock.db import users
from sherlock.db.connection import get_db
from sherlock.db.users import User
from sherlock.identity import current_user

router = APIRouter(tags=["me"])


class Settings(BaseModel):
    """User settings with the PRD §7.10 defaults. Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")

    theme: Literal["dark", "light", "system"] = "system"
    accent: Literal["verdigris", "arcane", "ember", "aether", "brass"] = "verdigris"
    chatbar: Literal["pinned", "autohide", "hidden"] = "pinned"
    after_upload: Literal["ask", "always", "never"] = "ask"
    cleaning_mode: Literal["auto", "stepwise"] = "auto"
    story_updates: Literal["auto", "ask"] = "auto"
    spotlight: Literal["off", "subtle", "full"] = "subtle"
    reduce_motion: Literal["system", "on", "off"] = "system"
    default_tab: Literal["csv", "dashboard", "flow"] = "dashboard"


class Me(BaseModel):
    user_id: str
    created_at: str
    settings: Settings


def effective_settings(stored: dict) -> Settings:
    """Stored values over the defaults; values no longer valid fall back to the default."""
    defaults = Settings().model_dump()
    merged = {}
    for key, default in defaults.items():
        candidate = {key: stored.get(key, default)}
        try:
            merged.update(Settings.model_validate(candidate).model_dump(include={key}))
        except ValueError:
            merged[key] = default
    return Settings(**merged)


@router.get("/me", response_model=Me)
def get_me(user: User = Depends(current_user)) -> Me:
    return Me(user_id=user.id, created_at=user.created_at, settings=effective_settings(user.settings))


@router.put("/me/settings", response_model=Settings)
def put_settings(
    body: Settings,
    request: Request,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> Settings:
    """Accepts a full or partial Settings; fields left out keep their stored value. Switching "Story
    updates" from Ask first to Automatic queues a cascade for each dataset with an outdated card or run,
    so they're brought up to date without a new edit (plan 2b.3)."""
    current = users.get(conn, user.id)
    stored = current.settings if current else {}
    before = effective_settings(stored).story_updates
    updated = effective_settings(stored | body.model_dump(exclude_unset=True))
    users.save_settings(conn, user.id, stored | updated.model_dump())  # keeps other keys, e.g. `notebook`
    if before == "ask" and updated.story_updates == "auto":
        from sherlock.jobs.cascade import queue_cascade

        for dataset in conn.execute(
                "SELECT * FROM datasets d WHERE d.user_id = ? AND d.deleted_at IS NULL AND (EXISTS (SELECT 1 FROM cards c "
                "WHERE c.dataset_id = d.id AND c.deleted_at IS NULL AND c.status = 'outdated') OR EXISTS (SELECT 1 FROM runs r "
                "WHERE r.dataset_id = d.id AND r.status = 'outdated'))", (user.id,)).fetchall():
            queue_cascade(conn, dataset, reason="settings")
        request.app.state.jobs.wake()
    return updated
