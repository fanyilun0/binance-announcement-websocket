"""Durable outbox for Binance announcements.

The WebSocket feed has no replay cursor.  An announcement therefore has to be
recorded before it is handed to an unreliable webhook, otherwise a short
webhook outage becomes a permanent lost notification.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List


class AnnouncementStore:
    """A small SQLite-backed, at-least-once delivery outbox."""

    def __init__(self, database_path: str):
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS announcements (
                announcement_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL,
                last_error TEXT,
                created_at REAL NOT NULL,
                sent_at REAL
            )
            """
        )
        self.connection.commit()

    def add(self, announcement_id: str, announcement: Dict[str, Any]) -> bool:
        """Persist an announcement once.  Returns True only for a new item."""
        now = time.time()
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO announcements
                (announcement_id, payload, status, next_attempt_at, created_at)
            VALUES (?, ?, 'pending', ?, ?)
            """,
            (announcement_id, json.dumps(announcement, ensure_ascii=False), now, now),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def due(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT announcement_id, payload, attempts
            FROM announcements
            WHERE status = 'pending' AND next_attempt_at <= ?
            ORDER BY created_at
            LIMIT ?
            """,
            (time.time(), limit),
        ).fetchall()
        return [
            {"announcement_id": row[0], "announcement": json.loads(row[1]), "attempts": row[2]}
            for row in rows
        ]

    def mark_sent(self, announcement_id: str) -> None:
        self.connection.execute(
            "UPDATE announcements SET status = 'sent', sent_at = ?, last_error = NULL WHERE announcement_id = ?",
            (time.time(), announcement_id),
        )
        self.connection.commit()

    def mark_failed(self, announcement_id: str, attempts: int, error: str) -> float:
        """Schedule the next attempt with capped exponential backoff."""
        delay = min(300, 2 ** min(attempts, 8))
        next_attempt_at = time.time() + delay
        self.connection.execute(
            """
            UPDATE announcements
            SET attempts = ?, next_attempt_at = ?, last_error = ?
            WHERE announcement_id = ?
            """,
            (attempts, next_attempt_at, error[:1000], announcement_id),
        )
        self.connection.commit()
        return delay

    def close(self) -> None:
        self.connection.close()
