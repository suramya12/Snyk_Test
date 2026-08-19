"""
Database management for download queue and history.

This module provides SQLite-based persistence for download items with support for:
- Queue management and ordering
- Full-text search
- Automatic schema migrations
- Optimized indexing
"""
from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from typing import List, Optional, Any
from contextlib import contextmanager
from .models import QueueItem, Status
from .config import CONFIG
from .logging_util import get_logger

log = get_logger("db")

# Only declare the table; don't create indexes until after migration.
SCHEMA = '''
CREATE TABLE IF NOT EXISTS downloads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL,
  title TEXT,
  status TEXT NOT NULL,
  filepath TEXT,
  added_at REAL,
  updated_at REAL,
  total_bytes INTEGER,
  downloaded_bytes INTEGER,
  speed REAL,
  eta INTEGER,
  errmsg TEXT,
  format TEXT,
  position INTEGER DEFAULT 0,
  thumb_path TEXT,
  uploader TEXT,
  duration INTEGER
);
'''

def _column_exists(con: sqlite3.Connection, table: str, col: str) -> bool:
    cur = con.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

class DB:
    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as con:
            # 1) Ensure table exists (no indexes yet)
            con.executescript(SCHEMA)

            # 2) Add missing columns for legacy DBs
            migrations = {
                "position": "INTEGER DEFAULT 0",
                "thumb_path": "TEXT",
                "uploader": "TEXT",
                "duration": "INTEGER",
            }
            for col, decl in migrations.items():
                if not _column_exists(con, "downloads", col):
                    con.execute(f"ALTER TABLE downloads ADD COLUMN {col} {decl}")

            # 3) Create indexes AFTER columns exist for optimal performance
            con.execute("CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_downloads_position ON downloads(position)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_downloads_status_position ON downloads(status, position)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_downloads_updated_at ON downloads(updated_at)")

            # Enable Write-Ahead Logging for better concurrency
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")

            log.info("Database initialized with optimized indexes")

            # 4) Seed position for rows lacking it
            con.execute("UPDATE downloads SET position = id WHERE position IS NULL OR position = 0")

    def add_queue_item(self, url: str, fmt: str) -> int:
        """
        Add a new download item to the queue.

        Args:
            url: The video URL to download
            fmt: Format string for video quality

        Returns:
            Database ID of the newly created item
        """
        now = time.time()
        try:
            with self._connect() as con:
                # compute next position
                (mx,) = con.execute("SELECT COALESCE(MAX(position), 0) FROM downloads").fetchone()
                pos = int(mx) + 1
                cur = con.execute(
                    "INSERT INTO downloads (url, status, added_at, updated_at, format, position) VALUES (?, ?, ?, ?, ?, ?)",
                    (url, "queued", now, now, fmt, pos),
                )
                item_id = cur.lastrowid
                log.debug(f"Added queue item {item_id} for URL: {url}")
                return item_id
        except sqlite3.Error as e:
            log.error(f"Database error adding queue item: {e}")
            raise

    def update(self, item_id: int, **fields: Any) -> None:
        """
        Update fields for a download item.

        Args:
            item_id: Database ID of the item to update
            **fields: Field names and values to update
        """
        if not fields:
            return
        fields["updated_at"] = time.time()
        keys = ", ".join([f"{k}=?" for k in fields.keys()])
        values = list(fields.values()) + [item_id]
        try:
            with self._connect() as con:
                con.execute(f"UPDATE downloads SET {keys} WHERE id=?", values)
        except sqlite3.Error as e:
            log.error(f"Database error updating item {item_id}: {e}")
            raise

    def get(self, item_id: int) -> Optional[QueueItem]:
        """
        Retrieve a single download item by ID.

        Args:
            item_id: Database ID of the item

        Returns:
            QueueItem if found, None otherwise
        """
        try:
            with self._connect() as con:
                row = con.execute("SELECT * FROM downloads WHERE id=?", (item_id,)).fetchone()
                return QueueItem(**dict(row)) if row else None
        except sqlite3.Error as e:
            log.error(f"Database error retrieving item {item_id}: {e}")
            return None

    def list(self, status: Optional[str] = None, limit: Optional[int] = None) -> list[QueueItem]:
        """
        List download items, optionally filtered by status.

        Args:
            status: Optional status filter (queued, downloading, completed, etc.)
            limit: Optional maximum number of items to return

        Returns:
            List of QueueItem objects ordered by position
        """
        try:
            with self._connect() as con:
                if status:
                    query = "SELECT * FROM downloads WHERE status=? ORDER BY position ASC"
                    params: tuple = (status,)
                else:
                    query = "SELECT * FROM downloads ORDER BY position ASC"
                    params = ()

                if limit:
                    query += f" LIMIT {limit}"

                rows = con.execute(query, params).fetchall()
                return [QueueItem(**dict(r)) for r in rows]
        except sqlite3.Error as e:
            log.error(f"Database error listing items: {e}")
            return []

    def search(self, term: str) -> list[QueueItem]:
        """
        Search for download items by URL, title, or filepath.

        Args:
            term: Search term to match

        Returns:
            List of matching QueueItem objects
        """
        if not term:
            return []

        like = f"%{term}%"
        try:
            with self._connect() as con:
                # Optimized search with UNION to better use indexes
                rows = con.execute(
                    """
                    SELECT * FROM downloads
                    WHERE url LIKE ? OR title LIKE ? OR filepath LIKE ? OR uploader LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT 100
                    """,
                    (like, like, like, like),
                ).fetchall()
                return [QueueItem(**dict(r)) for r in rows]
        except sqlite3.Error as e:
            log.error(f"Database error searching for term '{term}': {e}")
            return []

    def delete(self, item_id: int) -> None:
        """
        Delete a download item from the database.

        Args:
            item_id: Database ID of the item to delete
        """
        try:
            with self._connect() as con:
                con.execute("DELETE FROM downloads WHERE id=?", (item_id,))
                log.debug(f"Deleted item {item_id}")
        except sqlite3.Error as e:
            log.error(f"Database error deleting item {item_id}: {e}")
            raise

    def move_up(self, item_id: int) -> None:
        """
        Move a download item up in the queue.

        Args:
            item_id: Database ID of the item to move up
        """
        try:
            with self._connect() as con:
                row = con.execute("SELECT id, position FROM downloads WHERE id=?", (item_id,)).fetchone()
                if not row:
                    return
                pos = row["position"]
                above = con.execute(
                    "SELECT id, position FROM downloads WHERE position < ? ORDER BY position DESC LIMIT 1",
                    (pos,)
                ).fetchone()
                if not above:
                    return
                con.execute("UPDATE downloads SET position=? WHERE id=?", (above["position"], item_id))
                con.execute("UPDATE downloads SET position=? WHERE id=?", (pos, above["id"]))
        except sqlite3.Error as e:
            log.error(f"Database error moving item {item_id} up: {e}")
            raise

    def move_down(self, item_id: int) -> None:
        """
        Move a download item down in the queue.

        Args:
            item_id: Database ID of the item to move down
        """
        try:
            with self._connect() as con:
                row = con.execute("SELECT id, position FROM downloads WHERE id=?", (item_id,)).fetchone()
                if not row:
                    return
                pos = row["position"]
                below = con.execute(
                    "SELECT id, position FROM downloads WHERE position > ? ORDER BY position ASC LIMIT 1",
                    (pos,)
                ).fetchone()
                if not below:
                    return
                con.execute("UPDATE downloads SET position=? WHERE id=?", (below["position"], item_id))
                con.execute("UPDATE downloads SET position=? WHERE id=?", (pos, below["id"]))
        except sqlite3.Error as e:
            log.error(f"Database error moving item {item_id} down: {e}")
            raise

    def clear_history(self) -> None:
        """
        Remove completed, error, and canceled items from the database.

        This helps keep the database size manageable and improves query performance.
        """
        try:
            with self._connect() as con:
                result = con.execute(
                    "DELETE FROM downloads WHERE status IN (?, ?, ?)",
                    (
                        Status.COMPLETED.value,
                        Status.ERROR.value,
                        Status.CANCELED.value,
                    ),
                )
                deleted_count = result.rowcount
                log.info(f"Cleared {deleted_count} history items from database")

                # Optimize database after bulk delete
                con.execute("VACUUM")
        except sqlite3.Error as e:
            log.error(f"Database error clearing history: {e}")
            raise

    def get_statistics(self) -> dict[str, int]:
        """
        Get download statistics.

        Returns:
            Dictionary with counts for each status
        """
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT status, COUNT(*) as count FROM downloads GROUP BY status"
                ).fetchall()
                return {row["status"]: row["count"] for row in rows}
        except sqlite3.Error as e:
            log.error(f"Database error getting statistics: {e}")
            return {}

DB_INSTANCE = DB(CONFIG.db_file)
