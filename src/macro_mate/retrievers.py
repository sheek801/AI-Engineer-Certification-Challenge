"""Retrievers — hybrid search combining BM25 (sparse) and Qdrant (dense).

The EnsembleRetriever merges results from both retrievers using
weighted reciprocal rank fusion, giving you the best of both worlds:
  - BM25 excels at exact keyword matches (e.g. "Mifflin-St Jeor")
  - Dense retrieval excels at semantic meaning (e.g. "how many calories
    should I eat" matches content about TDEE even without that exact phrase)
"""

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever

from macro_mate.config import RETRIEVER_K, BM25_WEIGHT, DENSE_WEIGHT


def create_dense_retriever(vector_store: QdrantVectorStore):
    """Build a dense-only retriever for baseline evaluation."""
    return vector_store.as_retriever(search_kwargs={"k": RETRIEVER_K})


def create_ensemble_retriever(
    vector_store: QdrantVectorStore,
    documents: list[Document],
) -> EnsembleRetriever:
    """Build a hybrid retriever from a vector store and raw documents.

    Args:
        vector_store: The Qdrant store (from vector_store.py) for dense retrieval.
        documents: The same documents used to build the vector store —
                   BM25 needs the raw text, not embeddings.

    Returns:
        An EnsembleRetriever that merges BM25 + dense results.
    """
    dense_retriever = vector_store.as_retriever(search_kwargs={"k": RETRIEVER_K})
    print(f"[Retriever] Dense retriever ready (k={RETRIEVER_K})")

    bm25_retriever = BM25Retriever.from_documents(documents, k=RETRIEVER_K)
    print(f"[Retriever] BM25 retriever ready (k={RETRIEVER_K}, "
          f"{len(documents)} documents indexed)")

    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, dense_retriever],
        weights=[BM25_WEIGHT, DENSE_WEIGHT],
    )
    print(f"[Retriever] Ensemble retriever ready "
          f"(BM25={BM25_WEIGHT}, Dense={DENSE_WEIGHT})")

    return ensemble_retriever
