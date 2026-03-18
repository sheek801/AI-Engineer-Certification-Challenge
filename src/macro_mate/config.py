"""Centralised configuration — environment variables, model constants, and file paths.

Every other module imports from here so that magic strings and env-var
look-ups live in exactly one place.
"""

from pathlib import Path
from dotenv import load_dotenv
import os

# ── Load .env into os.environ ─────────────────────────────────────────
# override=False means real shell env vars take priority over the .env file
load_dotenv(override=True)

# ── API keys ──────────────────────────────────────────────────────────
# .get() with default "" lets the app import even when keys aren't set
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
TAVILY_API_KEY: str = os.environ.get("TAVILY_API_KEY", "")
LANGSMITH_API_KEY: str = os.environ.get("LANGSMITH_API_KEY", "")
USDA_API_KEY: str = os.environ.get("USDA_API_KEY", "")

# ── LangSmith tracing ────────────────────────────────────────────────
# The SDK reads these directly from os.environ, not from Python variables.
# setdefault only writes if the key isn't already set.
os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_PROJECT", "macromind")

# ── LLM / Embedding model names ──────────────────────────────────────
LLM_MODEL: str = "gpt-4o"
EMBEDDING_MODEL: str = "text-embedding-3-small"
EMBEDDING_DIMS: int = 1536

# ── Chunking parameters ──────────────────────────────────────────────
CHUNK_SIZE: int = 1000
CHUNK_OVERLAP: int = 200

# ── Qdrant vector store ──────────────────────────────────────────────
COLLECTION_NAME: str = "macromind"

# ── Retriever settings ───────────────────────────────────────────────
RETRIEVER_K: int = 5
BM25_WEIGHT: float = 0.5
DENSE_WEIGHT: float = 0.5

# ── File paths ────────────────────────────────────────────────────────
# Priority: DATA_DIR env var > computed from __file__ > cwd()/data
# The env var is needed in Docker where pip install puts config.py
# in site-packages, making the __file__-based path wrong.
_env_data_dir = os.environ.get("DATA_DIR")
if _env_data_dir:
    DATA_DIR: Path = Path(_env_data_dir)
else:
    _computed = Path(__file__).resolve().parents[2] / "data"
    DATA_DIR: Path = _computed if _computed.is_dir() else Path.cwd() / "data"

PROJECT_ROOT: Path = DATA_DIR.parent
NUTRITION_DIR: Path = DATA_DIR / "nutrition_science"
RECIPES_DIR: Path = DATA_DIR / "recipes"
RESTAURANT_DIR: Path = DATA_DIR / "restaurant_data"

# ── SQLite persistent store ─────────────────────────────────────────
# Env var allows Railway to mount a persistent volume at /data
SQLITE_DB_PATH: str = os.environ.get(
    "SQLITE_DB_PATH", str(DATA_DIR / "macro_mate.db")
)
