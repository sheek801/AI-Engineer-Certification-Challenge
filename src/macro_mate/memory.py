"""Memory — short-term (MemorySaver) and long-term (PersistentStore) factories.

Two types of memory, two different purposes:

  MemorySaver (checkpointer)
    Saves the graph state after each step. This is how the agent
    "remembers" earlier messages in the same conversation thread.

  PersistentStore (store)
    SQLite-backed storage that persists across server restarts.
    Stores user profiles, meal logs, and macro targets. Tools
    write to it and read from it. Uses hybrid search (vector +
    keyword) inspired by OpenClaw/Claudebot's memory architecture.
"""

from langgraph.checkpoint.memory import MemorySaver

from macro_mate.persistent_store import PersistentStore
from macro_mate.vector_store import get_embeddings
from macro_mate.config import EMBEDDING_DIMS, SQLITE_DB_PATH


def create_checkpointer() -> MemorySaver:
    """Create a checkpointer for short-term conversational memory."""
    return MemorySaver()


def create_memory_store() -> PersistentStore:
    """Create a persistent long-term store for user data.

    Data stored here (profiles, meal logs, etc.) survives server
    restarts because it lives in a SQLite file on disk.
    """
    embeddings = get_embeddings()
    return PersistentStore(
        db_path=SQLITE_DB_PATH,
        embeddings=embeddings,
        dims=EMBEDDING_DIMS,
    )
