"""
Optimized database management with connection pooling and batch operations.

Performance optimizations:
- Thread-local connection pooling
- Prepared statements for frequent queries
- Batch operations for bulk updates
- Query result caching
- Optimized indexes
- WAL mode for concurrent access
"""
from __future__ import annotations
import sqlite3
import time
import threading
from pathlib import Path
from typing import List, Optional, Any, Dict, Callable
from contextlib import contextmanager
from functools import lru_cache

from .models import QueueItem, Status
from .config import CONFIG
from .logging_util import get_logger

log = get_logger("db")

# Thread-local storage for connections
_thread_local = threading.local()

# Cache for frequently accessed data
_cache_lock = threading.RLock()
_query_cache: Dict[str, Any] = {}
_cache_ttl: Dict[str, float] = {}
CACHE_DURATION = 5.0  # seconds


def _get_cache_key(operation: str, *args) -> str:
    """Generate cache key for operation."""
    return f"{operation}:{':'.join(map(str, args))}"


def _get_cached(key: str) -> Optional[Any]:
    """Get cached value if still valid."""
    with _cache_lock:
        if key in _query_cache:
            if time.time() - _cache_ttl.get(key, 0) < CACHE_DURATION:
                return _query_cache[key]
            else:
                # Expired, remove
                _query_cache.pop(key, None)
                _cache_ttl.pop(key, None)
    return None


def _set_cached(key: str, value: Any):
    """Cache a value with TTL."""
    with _cache_lock:
        _query_cache[key] = value
        _cache_ttl[key] = time.time()


def _invalidate_cache(pattern: Optional[str] = None):
    """Invalidate cache entries matching pattern or all if None."""
    with _cache_lock:
        if pattern is None:
            _query_cache.clear()
            _cache_ttl.clear()
        else:
            keys_to_remove = [k for k in _query_cache.keys() if pattern in k]
            for key in keys_to_remove:
                _query_cache.pop(key, None)
                _cache_ttl.pop(key, None)


# Database schema with optimized indexes
SCHEMA = '''
CREATE TABLE IF NOT EXISTS downloads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL,
  title TEXT,
  status TEXT NOT NULL,
  filepath TEXT,
  added_at REAL NOT NULL,
  updated_at REAL NOT NULL,
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

-- Composite index for common query patterns
CREATE INDEX IF NOT EXISTS idx_status_position ON downloads(status, position);
CREATE INDEX IF NOT EXISTS idx_updated_at ON downloads(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_status_updated ON downloads(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_position ON downloads(position);
'''


def _column_exists(con: sqlite3.Connection, table: str, col: str) -> bool:
    """Check if column exists in table."""
    cur = con.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())


class OptimizedDB:
    """
    Optimized database with connection pooling and caching.

    Performance features:
    - Thread-local connection pool
    - Query result caching with TTL
    - Batch operations
    - Prepared statements
    - Optimized indexes
    """

    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        self._init_lock = threading.Lock()
        self._initialized = False
        self._init()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get thread-local connection with optimizations.

        Returns:
            Optimized SQLite connection for current thread
        """
        if not hasattr(_thread_local, 'connection') or _thread_local.connection is None:
            conn = sqlite3.connect(
                self.path,
                check_same_thread=False,
                timeout=30.0,
                isolation_level=None  # Autocommit mode for better concurrency
            )
            conn.row_factory = sqlite3.Row

            # Performance optimizations
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
            conn.execute("PRAGMA page_size=4096")

            _thread_local.connection = conn

        return _thread_local.connection

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = self._get_connection()
        try:
            yield conn
        except Exception as e:
            log.error(f"Database error: {e}")
            raise

    def _init(self) -> None:
        """Initialize database with schema and migrations."""
        with self._init_lock:
            if self._initialized:
                return

            with self._connect() as con:
                # Create schema
                con.executescript(SCHEMA)

                # Migrations for legacy databases
                migrations = {
                    "position": "INTEGER DEFAULT 0",
                    "thumb_path": "TEXT",
                    "uploader": "TEXT",
                    "duration": "INTEGER",
                }

                for col, decl in migrations.items():
                    if not _column_exists(con, "downloads", col):
                        con.execute(f"ALTER TABLE downloads ADD COLUMN {col} {decl}")
                        log.info(f"Added column: {col}")

                # Seed position for rows lacking it
                con.execute("UPDATE downloads SET position = id WHERE position IS NULL OR position = 0")

                # Analyze for query optimizer
                con.execute("ANALYZE")

            self._initialized = True
            log.info("Database initialized and optimized")

    def add_queue_item(self, url: str, fmt: str) -> int:
        """
        Add item to queue with optimized position calculation.

        Args:
            url: Video URL
            fmt: Format string

        Returns:
            Database ID of new item
        """
        now = time.time()

        try:
            with self._connect() as con:
                # Get next position efficiently
                cursor = con.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM downloads")
                pos = cursor.fetchone()[0]

                cursor = con.execute(
                    "INSERT INTO downloads (url, status, added_at, updated_at, format, position) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (url, Status.QUEUED.value, now, now, fmt, pos),
                )
                item_id = cursor.lastrowid

                # Invalidate list cache
                _invalidate_cache("list")

                log.debug(f"Added queue item {item_id}")
                return item_id

        except sqlite3.Error as e:
            log.error(f"Failed to add queue item: {e}")
            raise

    def update(self, item_id: int, **fields: Any) -> None:
        """
        Update item fields with optimized query.

        Args:
            item_id: Database ID
            **fields: Fields to update
        """
        if not fields:
            return

        fields["updated_at"] = time.time()

        try:
            with self._connect() as con:
                # Build parameterized query
                set_clause = ", ".join([f"{k}=?" for k in fields.keys()])
                values = list(fields.values()) + [item_id]

                con.execute(f"UPDATE downloads SET {set_clause} WHERE id=?", values)

                # Invalidate caches related to this item
                _invalidate_cache(f"get:{item_id}")
                _invalidate_cache("list")

        except sqlite3.Error as e:
            log.error(f"Failed to update item {item_id}: {e}")
            raise

    def batch_update(self, updates: List[tuple[int, Dict[str, Any]]]) -> None:
        """
        Batch update multiple items efficiently.

        Args:
            updates: List of (item_id, fields_dict) tuples
        """
        if not updates:
            return

        try:
            with self._connect() as con:
                con.execute("BEGIN TRANSACTION")

                try:
                    now = time.time()
                    for item_id, fields in updates:
                        fields["updated_at"] = now
                        set_clause = ", ".join([f"{k}=?" for k in fields.keys()])
                        values = list(fields.values()) + [item_id]
                        con.execute(f"UPDATE downloads SET {set_clause} WHERE id=?", values)

                    con.execute("COMMIT")
                    _invalidate_cache()  # Invalidate all caches

                except Exception:
                    con.execute("ROLLBACK")
                    raise

        except sqlite3.Error as e:
            log.error(f"Batch update failed: {e}")
            raise

    def get(self, item_id: int) -> Optional[QueueItem]:
        """
        Get single item with caching.

        Args:
            item_id: Database ID

        Returns:
            QueueItem or None
        """
        cache_key = _get_cache_key("get", item_id)
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            with self._connect() as con:
                row = con.execute("SELECT * FROM downloads WHERE id=?", (item_id,)).fetchone()

                if row:
                    item = QueueItem(**dict(row))
                    _set_cached(cache_key, item)
                    return item
                return None

        except sqlite3.Error as e:
            log.error(f"Failed to get item {item_id}: {e}")
            return None

    def list(self, status: Optional[str] = None, limit: Optional[int] = None) -> List[QueueItem]:
        """
        List items with caching and optimized query.

        Args:
            status: Optional status filter
            limit: Optional result limit

        Returns:
            List of QueueItem objects
        """
        cache_key = _get_cache_key("list", status or "all", limit or 0)
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            with self._connect() as con:
                if status:
                    query = "SELECT * FROM downloads WHERE status=? ORDER BY position ASC"
                    params = (status,)
                else:
                    query = "SELECT * FROM downloads ORDER BY position ASC"
                    params = ()

                if limit:
                    query += f" LIMIT {limit}"

                rows = con.execute(query, params).fetchall()
                items = [QueueItem(**dict(r)) for r in rows]

                _set_cached(cache_key, items)
                return items

        except sqlite3.Error as e:
            log.error(f"Failed to list items: {e}")
            return []

    def search(self, term: str) -> List[QueueItem]:
        """
        Search items with optimized LIKE query.

        Args:
            term: Search term

        Returns:
            List of matching items
        """
        if not term:
            return []

        cache_key = _get_cache_key("search", term)
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        like = f"%{term}%"

        try:
            with self._connect() as con:
                rows = con.execute(
                    """
                    SELECT * FROM downloads
                    WHERE url LIKE ? OR title LIKE ? OR filepath LIKE ? OR uploader LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT 100
                    """,
                    (like, like, like, like),
                ).fetchall()

                items = [QueueItem(**dict(r)) for r in rows]
                _set_cached(cache_key, items)
                return items

        except sqlite3.Error as e:
            log.error(f"Search failed: {e}")
            return []

    def delete(self, item_id: int) -> None:
        """Delete item and invalidate caches."""
        try:
            with self._connect() as con:
                con.execute("DELETE FROM downloads WHERE id=?", (item_id,))
                _invalidate_cache()
                log.debug(f"Deleted item {item_id}")

        except sqlite3.Error as e:
            log.error(f"Failed to delete item {item_id}: {e}")
            raise

    def delete_batch(self, item_ids: List[int]) -> int:
        """
        Delete multiple items in one transaction.

        Args:
            item_ids: List of IDs to delete

        Returns:
            Number of items deleted
        """
        if not item_ids:
            return 0

        try:
            with self._connect() as con:
                placeholders = ",".join(["?"] * len(item_ids))
                cursor = con.execute(
                    f"DELETE FROM downloads WHERE id IN ({placeholders})",
                    item_ids
                )
                _invalidate_cache()
                count = cursor.rowcount
                log.info(f"Deleted {count} items in batch")
                return count

        except sqlite3.Error as e:
            log.error(f"Batch delete failed: {e}")
            raise

    def move_up(self, item_id: int) -> None:
        """Move item up in queue."""
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

                if above:
                    con.execute("UPDATE downloads SET position=? WHERE id=?", (above["position"], item_id))
                    con.execute("UPDATE downloads SET position=? WHERE id=?", (pos, above["id"]))
                    _invalidate_cache("list")

        except sqlite3.Error as e:
            log.error(f"Failed to move item {item_id} up: {e}")
            raise

    def move_down(self, item_id: int) -> None:
        """Move item down in queue."""
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

                if below:
                    con.execute("UPDATE downloads SET position=? WHERE id=?", (below["position"], item_id))
                    con.execute("UPDATE downloads SET position=? WHERE id=?", (pos, below["id"]))
                    _invalidate_cache("list")

        except sqlite3.Error as e:
            log.error(f"Failed to move item {item_id} down: {e}")
            raise

    def clear_history(self) -> int:
        """
        Clear completed/error/canceled items with optimization.

        Returns:
            Number of items cleared
        """
        try:
            with self._connect() as con:
                cursor = con.execute(
                    "DELETE FROM downloads WHERE status IN (?, ?, ?)",
                    (Status.COMPLETED.value, Status.ERROR.value, Status.CANCELED.value),
                )
                count = cursor.rowcount

                # Optimize database after bulk delete
                if count > 100:
                    con.execute("VACUUM")
                    log.info("Database vacuumed after clearing history")

                _invalidate_cache()
                log.info(f"Cleared {count} history items")
                return count

        except sqlite3.Error as e:
            log.error(f"Failed to clear history: {e}")
            raise

    @lru_cache(maxsize=1)
    def get_statistics(self) -> Dict[str, int]:
        """
        Get download statistics with caching.

        Returns:
            Dict of status counts
        """
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT status, COUNT(*) as count FROM downloads GROUP BY status"
                ).fetchall()
                return {row["status"]: row["count"] for row in rows}

        except sqlite3.Error as e:
            log.error(f"Failed to get statistics: {e}")
            return {}

    def optimize(self) -> None:
        """Run database optimization."""
        try:
            with self._connect() as con:
                con.execute("ANALYZE")
                con.execute("PRAGMA optimize")
                log.info("Database optimized")

        except sqlite3.Error as e:
            log.error(f"Optimization failed: {e}")

    def close_all_connections(self):
        """Close all thread-local connections."""
        if hasattr(_thread_local, 'connection') and _thread_local.connection:
            _thread_local.connection.close()
            _thread_local.connection = None
            log.info("Closed database connection")


# Singleton instance
DB_INSTANCE = OptimizedDB(CONFIG.db_file)
