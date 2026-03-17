"""PersistentStore — SQLite-backed long-term memory with hybrid search.

Replaces LangGraph's InMemoryStore so user data (profiles, meal logs,
macro targets) survives server restarts. Inspired by OpenClaw/Claudebot's
persistent memory architecture, adapted for structured nutrition data.

Three storage layers in one SQLite file:
  1. `items` table — core key-value rows (namespace, key, JSON value)
  2. `items_vec` virtual table (sqlite-vec) — vector embeddings for semantic search
  3. `items_fts` virtual table (FTS5) — full-text index for keyword search

Search uses hybrid scoring: 0.7 * vector_similarity + 0.3 * BM25.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from struct import pack
from typing import Any, Iterable

from langchain_core.embeddings import Embeddings
from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)

import sqlite_vec


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _serialize_namespace(ns: tuple[str, ...]) -> str:
    """Serialize a namespace tuple to a JSON string for SQLite TEXT storage."""
    return json.dumps(list(ns))


def _deserialize_namespace(ns_str: str) -> tuple[str, ...]:
    """Deserialize a JSON string back to a namespace tuple."""
    return tuple(json.loads(ns_str))


def _serialize_f32(vector: list[float]) -> bytes:
    """Pack a float32 vector into bytes for sqlite-vec."""
    return pack(f"{len(vector)}f", *vector)


def _sanitize_fts_query(query: str) -> str:
    """Wrap a query in double-quotes so FTS5 treats it as a phrase.

    This avoids syntax errors from special chars (parentheses, colons, etc.)
    that FTS5 would otherwise interpret as operators.
    """
    # Escape any internal double-quotes
    escaped = query.replace('"', '""')
    return f'"{escaped}"'


# ═══════════════════════════════════════════════════════════════════════════
# PersistentStore
# ═══════════════════════════════════════════════════════════════════════════

class PersistentStore(BaseStore):
    """SQLite-backed store with hybrid vector + keyword search.

    Drop-in replacement for InMemoryStore. All tools that call
    store.put / store.get / store.search work unchanged.

    Args:
        db_path: Path to the SQLite database file.
        embeddings: LangChain Embeddings instance for vector indexing.
        dims: Embedding dimensions (1536 for text-embedding-3-small).
    """

    def __init__(
        self,
        db_path: str,
        embeddings: Embeddings | None = None,
        dims: int = 1536,
    ) -> None:
        self.db_path = db_path
        self.embeddings = embeddings
        self.dims = dims
        self._lock = threading.Lock()

        # Open connection with WAL mode for Chainlit concurrency
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")

        # Load sqlite-vec extension
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)

        self._create_tables()

    def _create_tables(self) -> None:
        """Create the three tables if they don't exist."""
        with self._lock:
            cur = self._conn.cursor()

            # Core key-value table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    text_content TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, key)
                )
            """)

            # Vector table for semantic search
            cur.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS items_vec
                USING vec0(
                    embedding float[{self.dims}] distance_metric=cosine
                )
            """)

            # FTS5 table for keyword search
            cur.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS items_fts
                USING fts5(
                    namespace,
                    key,
                    text_content,
                    content='items',
                    content_rowid='rowid'
                )
            """)

            # Triggers to keep FTS5 in sync with items table
            cur.executescript("""
                CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
                    INSERT INTO items_fts(rowid, namespace, key, text_content)
                    VALUES (new.rowid, new.namespace, new.key, new.text_content);
                END;

                CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
                    INSERT INTO items_fts(items_fts, rowid, namespace, key, text_content)
                    VALUES ('delete', old.rowid, old.namespace, old.key, old.text_content);
                END;

                CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
                    INSERT INTO items_fts(items_fts, rowid, namespace, key, text_content)
                    VALUES ('delete', old.rowid, old.namespace, old.key, old.text_content);
                    INSERT INTO items_fts(rowid, namespace, key, text_content)
                    VALUES (new.rowid, new.namespace, new.key, new.text_content);
                END;
            """)

            self._conn.commit()

    # ───────────────────────────────────────────────────────────────────
    # batch() — the only abstract method we must implement
    # ───────────────────────────────────────────────────────────────────

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        """Execute multiple operations synchronously in a single batch."""
        results: list[Result] = []

        with self._lock:
            for op in ops:
                if isinstance(op, GetOp):
                    results.append(self._handle_get(op))
                elif isinstance(op, PutOp):
                    self._handle_put(op)
                    results.append(None)
                elif isinstance(op, SearchOp):
                    results.append(self._handle_search(op))
                elif isinstance(op, ListNamespacesOp):
                    results.append(self._handle_list_namespaces(op))
                else:
                    raise ValueError(f"Unknown operation type: {type(op)}")

            self._conn.commit()

        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        """Async version — delegates to sync batch (SQLite is sync)."""
        return self.batch(ops)

    # ───────────────────────────────────────────────────────────────────
    # GetOp handler
    # ───────────────────────────────────────────────────────────────────

    def _handle_get(self, op: GetOp) -> Item | None:
        ns_str = _serialize_namespace(op.namespace)
        row = self._conn.execute(
            "SELECT value, created_at, updated_at FROM items "
            "WHERE namespace = ? AND key = ?",
            (ns_str, op.key),
        ).fetchone()

        if row is None:
            return None

        return Item(
            namespace=op.namespace,
            key=op.key,
            value=json.loads(row[0]),
            created_at=datetime.fromisoformat(row[1]),
            updated_at=datetime.fromisoformat(row[2]),
        )

    # ───────────────────────────────────────────────────────────────────
    # PutOp handler
    # ───────────────────────────────────────────────────────────────────

    def _handle_put(self, op: PutOp) -> None:
        ns_str = _serialize_namespace(op.namespace)
        now = datetime.now(timezone.utc).isoformat()

        # Delete operation
        if op.value is None:
            # Get the rowid before deleting (for vec table cleanup)
            row = self._conn.execute(
                "SELECT rowid FROM items WHERE namespace = ? AND key = ?",
                (ns_str, op.key),
            ).fetchone()
            if row:
                rowid = row[0]
                self._conn.execute(
                    "DELETE FROM items WHERE namespace = ? AND key = ?",
                    (ns_str, op.key),
                )
                # Clean up vector table
                self._conn.execute(
                    "DELETE FROM items_vec WHERE rowid = ?", (rowid,)
                )
            return

        # Extract text content for indexing
        text_content = ""
        if op.index is not False:
            # Default: index the "text" field if present
            if isinstance(op.index, list):
                # Index specific fields
                parts = []
                for field_path in op.index:
                    val = op.value.get(field_path, "")
                    if isinstance(val, str):
                        parts.append(val)
                text_content = " ".join(parts)
            else:
                # Default behavior: use "text" field
                text_content = op.value.get("text", "")

        value_json = json.dumps(op.value)

        # Check if item already exists
        existing = self._conn.execute(
            "SELECT rowid, created_at FROM items WHERE namespace = ? AND key = ?",
            (ns_str, op.key),
        ).fetchone()

        if existing:
            rowid = existing[0]
            created_at = existing[1]
            # Update existing item
            self._conn.execute(
                "UPDATE items SET value = ?, text_content = ?, updated_at = ? "
                "WHERE namespace = ? AND key = ?",
                (value_json, text_content, now, ns_str, op.key),
            )
            # Update vector if we have text to embed
            if text_content and self.embeddings and op.index is not False:
                embedding = self.embeddings.embed_query(text_content)
                vec_bytes = _serialize_f32(embedding)
                # Delete old vector and insert new one
                self._conn.execute(
                    "DELETE FROM items_vec WHERE rowid = ?", (rowid,)
                )
                self._conn.execute(
                    "INSERT INTO items_vec(rowid, embedding) VALUES (?, ?)",
                    (rowid, vec_bytes),
                )
        else:
            # Insert new item
            cur = self._conn.execute(
                "INSERT INTO items (namespace, key, value, text_content, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (ns_str, op.key, value_json, text_content, now, now),
            )
            rowid = cur.lastrowid

            # Embed and store vector if we have text
            if text_content and self.embeddings and op.index is not False:
                embedding = self.embeddings.embed_query(text_content)
                vec_bytes = _serialize_f32(embedding)
                self._conn.execute(
                    "INSERT INTO items_vec(rowid, embedding) VALUES (?, ?)",
                    (rowid, vec_bytes),
                )

    # ───────────────────────────────────────────────────────────────────
    # SearchOp handler — hybrid vector + FTS5
    # ───────────────────────────────────────────────────────────────────

    def _handle_search(self, op: SearchOp) -> list[SearchItem]:
        ns_prefix_str = _serialize_namespace(op.namespace_prefix)
        # For prefix matching: ["user1", "consumption"] should match
        # ["user1", "consumption"] exactly, but also be a prefix approach.
        # We use LIKE on the JSON array: '["user1", "consumption"' matches
        # '["user1", "consumption"]' and '["user1", "consumption", "sub"]'
        # Strip the trailing ']' for prefix matching
        ns_like = ns_prefix_str.rstrip("]") + "%"

        if op.query and self.embeddings:
            return self._hybrid_search(op, ns_like)
        else:
            return self._list_search(op, ns_like)

    def _list_search(
        self, op: SearchOp, ns_like: str
    ) -> list[SearchItem]:
        """List items by namespace prefix (no semantic query)."""
        query = (
            "SELECT namespace, key, value, created_at, updated_at "
            "FROM items WHERE namespace LIKE ? "
            "ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        )
        rows = self._conn.execute(
            query, (ns_like, op.limit, op.offset)
        ).fetchall()

        results = []
        for row in rows:
            item = SearchItem(
                namespace=_deserialize_namespace(row[0]),
                key=row[1],
                value=json.loads(row[2]),
                created_at=datetime.fromisoformat(row[3]),
                updated_at=datetime.fromisoformat(row[4]),
                score=None,
            )
            if self._matches_filter(item.value, op.filter):
                results.append(item)

        return results

    def _hybrid_search(
        self, op: SearchOp, ns_like: str
    ) -> list[SearchItem]:
        """Hybrid search: 0.7 * vector similarity + 0.3 * BM25 score."""
        assert self.embeddings is not None

        # Embed the query
        query_embedding = self.embeddings.embed_query(op.query)  # type: ignore[arg-type]
        query_vec = _serialize_f32(query_embedding)

        # ── Vector search (KNN) ──────────────────────────────────────
        # Get more candidates than limit for re-ranking after fusion
        k = min(op.limit * 5, 100)

        vec_results: dict[int, float] = {}  # rowid -> distance
        try:
            rows = self._conn.execute(
                "SELECT v.rowid, v.distance "
                "FROM items_vec v "
                "INNER JOIN items i ON v.rowid = i.rowid "
                "WHERE v.embedding MATCH ? "
                "AND k = ? "
                "AND i.namespace LIKE ?",
                (query_vec, k, ns_like),
            ).fetchall()
            for rowid, distance in rows:
                vec_results[rowid] = distance
        except Exception:
            # If vec search fails (empty table, etc.), continue with FTS only
            pass

        # ── FTS5 search (BM25) ───────────────────────────────────────
        fts_results: dict[int, float] = {}  # rowid -> rank
        if op.query:
            sanitized = _sanitize_fts_query(op.query)
            try:
                # FTS5 rank is negative (more negative = better match)
                ns_like_fts = ns_like
                rows = self._conn.execute(
                    "SELECT f.rowid, f.rank "
                    "FROM items_fts f "
                    "INNER JOIN items i ON f.rowid = i.rowid "
                    "WHERE items_fts MATCH ? "
                    "AND i.namespace LIKE ? "
                    "LIMIT ?",
                    (sanitized, ns_like_fts, k),
                ).fetchall()
                for rowid, rank in rows:
                    fts_results[rowid] = rank
            except Exception:
                # FTS query might fail on unusual input; continue
                pass

        # ── Score fusion ─────────────────────────────────────────────
        all_rowids = set(vec_results.keys()) | set(fts_results.keys())
        if not all_rowids:
            # Fall back to listing
            return self._list_search(op, ns_like)

        # Normalize vector distances to [0, 1] similarity scores
        # Cosine distance: 0 = identical, 2 = opposite
        # Convert to similarity: 1 - (distance / 2)
        vec_scores: dict[int, float] = {}
        if vec_results:
            for rowid, dist in vec_results.items():
                vec_scores[rowid] = 1.0 - (dist / 2.0)

        # Normalize FTS ranks to [0, 1]
        # FTS5 rank is negative; more negative = better
        fts_scores: dict[int, float] = {}
        if fts_results:
            min_rank = min(fts_results.values())
            max_rank = max(fts_results.values())
            rank_range = max_rank - min_rank if max_rank != min_rank else 1.0
            for rowid, rank in fts_results.items():
                # Invert so higher = better, normalize to [0, 1]
                fts_scores[rowid] = (max_rank - rank) / rank_range

        # Fuse: 0.7 * vector + 0.3 * BM25
        fused: dict[int, float] = {}
        for rowid in all_rowids:
            v_score = vec_scores.get(rowid, 0.0)
            f_score = fts_scores.get(rowid, 0.0)
            fused[rowid] = 0.7 * v_score + 0.3 * f_score

        # Sort by fused score descending
        sorted_rowids = sorted(fused.keys(), key=lambda r: fused[r], reverse=True)

        # Fetch items and build SearchItem results
        results: list[SearchItem] = []
        for rowid in sorted_rowids:
            row = self._conn.execute(
                "SELECT namespace, key, value, created_at, updated_at "
                "FROM items WHERE rowid = ?",
                (rowid,),
            ).fetchone()
            if row is None:
                continue

            value = json.loads(row[2])
            if not self._matches_filter(value, op.filter):
                continue

            results.append(SearchItem(
                namespace=_deserialize_namespace(row[0]),
                key=row[1],
                value=value,
                created_at=datetime.fromisoformat(row[3]),
                updated_at=datetime.fromisoformat(row[4]),
                score=fused[rowid],
            ))

            if len(results) >= op.limit:
                break

        return results[op.offset:]

    # ───────────────────────────────────────────────────────────────────
    # ListNamespacesOp handler
    # ───────────────────────────────────────────────────────────────────

    def _handle_list_namespaces(
        self, op: ListNamespacesOp
    ) -> list[tuple[str, ...]]:
        """List distinct namespaces matching the given conditions."""
        rows = self._conn.execute(
            "SELECT DISTINCT namespace FROM items"
        ).fetchall()

        namespaces = [_deserialize_namespace(row[0]) for row in rows]

        # Apply match conditions if any
        if op.match_conditions:
            filtered = []
            for ns in namespaces:
                if self._namespace_matches(ns, op.match_conditions):
                    filtered.append(ns)
            namespaces = filtered

        # Apply max_depth
        if op.max_depth is not None:
            namespaces = [ns[:op.max_depth] for ns in namespaces]
            # Deduplicate after truncation
            namespaces = list(set(namespaces))

        # Sort for deterministic output
        namespaces.sort()

        # Apply pagination
        start = op.offset
        end = start + op.limit if op.limit else None
        return namespaces[start:end]

    # ───────────────────────────────────────────────────────────────────
    # Filter helpers
    # ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _matches_filter(
        value: dict[str, Any], filter_dict: dict[str, Any] | None
    ) -> bool:
        """Check if a value dict matches the given filter conditions."""
        if not filter_dict:
            return True

        for key, condition in filter_dict.items():
            item_val = value.get(key)

            if isinstance(condition, dict):
                # Operator-based comparison
                for op_name, op_val in condition.items():
                    if op_name == "$eq" and item_val != op_val:
                        return False
                    elif op_name == "$ne" and item_val == op_val:
                        return False
                    elif op_name == "$gt" and (
                        item_val is None or item_val <= op_val
                    ):
                        return False
                    elif op_name == "$gte" and (
                        item_val is None or item_val < op_val
                    ):
                        return False
                    elif op_name == "$lt" and (
                        item_val is None or item_val >= op_val
                    ):
                        return False
                    elif op_name == "$lte" and (
                        item_val is None or item_val > op_val
                    ):
                        return False
            else:
                # Exact match
                if item_val != condition:
                    return False

        return True

    @staticmethod
    def _namespace_matches(
        ns: tuple[str, ...], conditions: tuple
    ) -> bool:
        """Check if a namespace matches ListNamespacesOp conditions."""
        # Conditions are tuples of MatchCondition objects
        for cond in conditions:
            match_type = cond.match_type if hasattr(cond, "match_type") else None
            path = cond.path if hasattr(cond, "path") else None

            if match_type == "prefix" and path:
                if not ns[: len(path)] == tuple(path):
                    return False
            elif match_type == "suffix" and path:
                if not ns[-len(path) :] == tuple(path):
                    return False
        return True

    # ───────────────────────────────────────────────────────────────────
    # Cleanup
    # ───────────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
