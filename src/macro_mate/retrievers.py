"""Retrievers — hybrid search combining BM25 (sparse) and Qdrant (dense).

The EnsembleRetriever merges results from both retrievers using
weighted reciprocal rank fusion, giving you the best of both worlds:
  - BM25 excels at exact keyword matches (e.g. "Mifflin-St Jeor")
  - Dense retrieval excels at semantic meaning (e.g. "how many calories
    should I eat" matches content about TDEE even without that exact phrase)

An optional Cohere reranker can be layered on top to filter the ensemble
results down to the most relevant chunks, improving context precision.
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


def create_reranked_ensemble_retriever(
    vector_store: QdrantVectorStore,
    documents: list[Document],
    cohere_api_key: str,
    top_n: int = 3,
):
    """Build a hybrid retriever with Cohere reranking on top.

    The ensemble retriever fetches k=5 candidates from BM25 + dense,
    then the Cohere reranker scores and filters to the top_n most
    relevant chunks. This improves context precision by removing
    tangential results before they reach the LLM.

    Args:
        vector_store: The Qdrant store for dense retrieval.
        documents: Raw documents for BM25.
        cohere_api_key: Cohere API key for the reranker.
        top_n: Number of documents to keep after reranking (default 3).

    Returns:
        A ContextualCompressionRetriever wrapping the ensemble.
    """
    from langchain.retrievers import ContextualCompressionRetriever
    from langchain_cohere import CohereRerank

    base = create_ensemble_retriever(vector_store, documents)

    reranker = CohereRerank(
        cohere_api_key=cohere_api_key,
        top_n=top_n,
        model="rerank-v3.5",
    )

    reranked = ContextualCompressionRetriever(
        base_compressor=reranker,
        base_retriever=base,
    )
    print(f"[Retriever] Cohere reranker active (top_n={top_n})")

    return reranked
