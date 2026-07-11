from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import AudioMode, DelaySettings, SpeakerProfile, SpeakerSelection, VolumeSettings


def default_data_dir() -> Path:
    configured = os.environ.get("TWINSYNC_DATA_DIR")
    if configured:
        return Path(configured)
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "TwinSyncAudio"
    return Path.cwd() / "data"


class TwinSyncDatabase:
    def __init__(self, path: Path | None = None) -> None:
        requested_path = path or default_data_dir() / "twinsync.sqlite3"
        try:
            requested_path.parent.mkdir(parents=True, exist_ok=True)
            self.path = requested_path
        except OSError:
            fallback_path = Path.cwd() / "data" / "twinsync.sqlite3"
            fallback_path.parent.mkdir(parents=True, exist_ok=True)
            self.path = fallback_path
        self._initialise()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialise(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def set_setting(self, key: str, value: Any) -> None:
        payload = json.dumps(value, sort_keys=True)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, payload),
            )

    def save_profile(self, profile: SpeakerProfile) -> int:
        payload = json.dumps(profile.to_dict(), sort_keys=True)
        with self._connect() as db:
            row = db.execute(
                """
                INSERT INTO profiles (name, payload, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                (profile.name, payload),
            ).fetchone()
        if row is None:
            raise RuntimeError("SQLite did not return the saved profile id.")
        return int(row["id"])

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT id, name, payload, updated_at FROM profiles ORDER BY name").fetchall()
        profiles: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload"])
            payload["id"] = int(row["id"])
            payload["updated_at"] = row["updated_at"]
            profiles.append(payload)
        return profiles

    def get_profile(self, profile_id: int) -> SpeakerProfile:
        with self._connect() as db:
            row = db.execute("SELECT id, payload FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if row is None:
            raise KeyError(f"Profile {profile_id} was not found.")
        payload = json.loads(row["payload"])
        payload["id"] = int(row["id"])
        return SpeakerProfile.from_dict(payload)

    def log_event(self, category: str, message: str, payload: dict[str, Any] | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO events (category, message, payload) VALUES (?, ?, ?)",
                (category, message, json.dumps(payload or {}, sort_keys=True)),
            )

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, category, message, payload, created_at
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "category": row["category"],
                "message": row["message"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def default_profile() -> SpeakerProfile:
    return SpeakerProfile(
        name="Default Pair",
        selection=SpeakerSelection(),
        delay=DelaySettings(),
        volume=VolumeSettings(),
        audio_mode=AudioMode(),
    )
