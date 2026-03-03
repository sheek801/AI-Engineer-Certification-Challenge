"""Generate a synthetic evaluation dataset using RAGAS TestsetGenerator.

This script reads all ingested documents, feeds them to RAGAS, and
produces question/ground-truth pairs that cover all three data tiers.
The output is saved as a JSONL file so it can be reused across
multiple evaluation runs without re-generating (and re-spending tokens).

Usage:
    python -m macro_mate.eval_dataset
"""

from pathlib import Path

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.testset import TestsetGenerator

from macro_mate.config import LLM_MODEL, EMBEDDING_MODEL, PROJECT_ROOT
from macro_mate.data_loader import load_all_documents


EVAL_DIR = PROJECT_ROOT / "eval"
TESTSET_PATH = EVAL_DIR / "testset.jsonl"
TESTSET_SIZE = 20


def build_generator() -> TestsetGenerator:
    """Create a RAGAS TestsetGenerator backed by the same models the app uses."""
    llm = LangchainLLMWrapper(ChatOpenAI(model=LLM_MODEL, temperature=0))
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=EMBEDDING_MODEL))
    return TestsetGenerator(llm=llm, embedding_model=embeddings)


def generate_testset():
    """Load documents, generate synthetic QA pairs, and save to disk."""
    print("[Eval] Loading documents …")
    documents = load_all_documents()

    print(f"[Eval] Generating {TESTSET_SIZE} synthetic test samples …")
    generator = build_generator()
    testset = generator.generate_with_langchain_docs(documents, testset_size=TESTSET_SIZE)

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    testset.to_pandas().to_json(TESTSET_PATH, orient="records", lines=True)

    df = testset.to_pandas()
    print(f"[Eval] Saved {len(df)} test samples to {TESTSET_PATH}")
    for i, row in df.head(3).iterrows():
        print(f"  Sample {i+1}: {row['user_input'][:80]}…")

    return testset


if __name__ == "__main__":
    generate_testset()
