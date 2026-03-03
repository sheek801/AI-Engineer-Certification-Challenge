"""Vector store — Qdrant in-memory with a single collection for all data.

This module creates one Qdrant collection that holds Documents from ALL
three data tiers (nutrition science, recipes, restaurant data).
The rest of the app only sees a QdrantVectorStore object — it doesn't
know or care that three different data sources are mixed inside.
"""

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from macro_mate.config import (
    EMBEDDING_MODEL,
    EMBEDDING_DIMS,
    COLLECTION_NAME,
)


def get_embeddings() -> OpenAIEmbeddings:
    """Create the embedding model used across the application.

    Separated into its own function because both the vector store AND
    the InMemoryStore (long-term memory) need the same embeddings.
    """
    return OpenAIEmbeddings(model=EMBEDDING_MODEL)


def create_vector_store(documents: list[Document]) -> QdrantVectorStore:
    """Create an in-memory Qdrant collection and load all documents into it.

    Args:
        documents: Combined list from data_loader.load_all_documents().

    Returns:
        A QdrantVectorStore ready for retrieval.
    """
    embeddings = get_embeddings()

    qdrant_client = QdrantClient(":memory:")

    qdrant_client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=EMBEDDING_DIMS,
            distance=Distance.COSINE,
        ),
    )

    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
    )

    vector_store.add_documents(documents)
    print(f"[Vector Store] Added {len(documents)} documents to '{COLLECTION_NAME}'")

    return vector_store
