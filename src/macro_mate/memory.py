"""Memory — short-term (MemorySaver) and long-term (InMemoryStore) factories.

Two types of memory, two different purposes:

  MemorySaver (checkpointer)
    Saves the graph state after each step. This is how the agent
    "remembers" earlier messages in the same conversation thread.

  InMemoryStore (store)
    Persists data across conversations — user profiles, meal logs,
    macro targets. Your tools write to it and read from it.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from macro_mate.vector_store import get_embeddings
from macro_mate.config import EMBEDDING_DIMS


def create_checkpointer() -> MemorySaver:
    """Create a checkpointer for short-term conversational memory."""
    return MemorySaver()


def create_memory_store() -> InMemoryStore:
    """Create a long-term store for user data (profiles, meal logs, etc.)."""
    embeddings = get_embeddings()
    return InMemoryStore(
        index={
            "embed": embeddings,
            "dims": EMBEDDING_DIMS,
        }
    )
