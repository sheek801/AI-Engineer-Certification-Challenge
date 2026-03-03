"""Data loading — ingest PDFs, text files, and CSVs into LangChain Documents.

All three data tiers produce the same output type: list[Document].
By loading everything here, the rest of the app doesn't care whether
a Document came from a PDF, a recipe CSV, or a fast-food CSV.
They all go into one Qdrant collection, searched by one retriever.

THREE TIERS:
  Tier 1  Nutrition science PDFs & text files  → chunked with text splitter
  Tier 2  Food.com recipes CSV                 → each row → one Document
  Tier 3  Fast-food restaurant CSV             → each row → one Document

Every Document carries a `source_type` metadata field so the agent's
tools can filter by origin if needed.
"""

from pathlib import Path
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import pandas as pd

from macro_mate.config import (
    NUTRITION_DIR,
    RECIPES_DIR,
    RESTAURANT_DIR,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)

# Minimum character length for a document to be worth embedding
MIN_CONTENT_LENGTH = 50


# ═══════════════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════════════

def _find_csv(directory: Path) -> Path:
    """Return the first CSV file found in a directory."""
    csvs = sorted(directory.glob("*.csv"))
    if not csvs:
        raise FileNotFoundError(f"No CSV files found in {directory}")
    return csvs[0]


def _quality_filter(docs: list[Document], tier_name: str) -> list[Document]:
    """Remove documents that are too short or empty to produce useful embeddings.

    Borrowed from the office-hours pattern: filter out junk *before* it
    reaches the vector store so retrieval quality stays high.
    """
    before = len(docs)
    filtered = [
        doc for doc in docs
        if doc.page_content.strip()
        and len(doc.page_content.strip()) >= MIN_CONTENT_LENGTH
    ]
    removed = before - len(filtered)
    if removed:
        print(f"  [{tier_name}] Quality filter removed {removed} docs "
              f"(< {MIN_CONTENT_LENGTH} chars or empty)")
    return filtered


# ═══════════════════════════════════════════════════════════════════════
# Tier 1 — Nutrition-science PDFs and text files
# ═══════════════════════════════════════════════════════════════════════

def load_nutrition_documents() -> list[Document]:
    """Load every PDF and TXT file in the nutrition_science directory.

    Pipeline:
      1. Walk the directory for .pdf and .txt files
      2. Use PyPDFLoader for PDFs (one Document per page)
         Use TextLoader for .txt files (one Document per file)
      3. Split with RecursiveCharacterTextSplitter(1000/200)
      4. Tag every chunk with source_type="nutrition_science"
      5. Quality-filter out empty/tiny chunks
    """
    raw_docs: list[Document] = []

    for file_path in sorted(NUTRITION_DIR.iterdir()):
        if file_path.suffix.lower() == ".pdf":
            loader = PyPDFLoader(str(file_path))
            raw_docs.extend(loader.load())
        elif file_path.suffix.lower() == ".txt":
            loader = TextLoader(str(file_path), encoding="utf-8")
            raw_docs.extend(loader.load())

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    split_docs = splitter.split_documents(raw_docs)

    for doc in split_docs:
        doc.metadata["source_type"] = "nutrition_science"

    split_docs = _quality_filter(split_docs, "Tier 1")

    print(f"[Tier 1] Nutrition science: {len(split_docs)} chunks "
          f"from {len(raw_docs)} raw pages/files")
    return split_docs


# ═══════════════════════════════════════════════════════════════════════
# Tier 2 — Food.com recipes CSV
# ═══════════════════════════════════════════════════════════════════════

def _parse_nutrition(nutrition_str: str) -> dict:
    """Parse the Food.com nutrition column into readable macro values.

    The column stores a string like '[calories, fat_%DV, sugar_%DV,
    sodium_%DV, protein_%DV, sat_fat_%DV, carbs_%DV]'.
    We convert %DV to approximate grams using FDA daily values.
    """
    import ast
    try:
        vals = ast.literal_eval(nutrition_str)
        if not isinstance(vals, list) or len(vals) < 7:
            return {}
        return {
            "calories": round(vals[0]),
            "total_fat_g": round(vals[1] * 78 / 100, 1),
            "sugar_g": round(vals[2] * 50 / 100, 1),
            "sodium_mg": round(vals[3] * 2300 / 100),
            "protein_g": round(vals[4] * 50 / 100, 1),
            "saturated_fat_g": round(vals[5] * 20 / 100, 1),
            "carbs_g": round(vals[6] * 275 / 100, 1),
        }
    except (ValueError, SyntaxError):
        return {}


def _recipe_to_narrative(row: pd.Series) -> str:
    """Convert one CSV row into a readable narrative string.

    The Food.com CSV stores ingredients and steps as string
    representations of Python lists (e.g. "['chicken', 'yogurt']"),
    so we include them as-is — the embedding model handles it fine.
    """
    parts = [f"Recipe: {row.get('name', 'Unknown')}"]

    if "minutes" in row and pd.notna(row["minutes"]):
        parts.append(f"Cook time: {int(row['minutes'])} minutes")

    if "nutrition" in row and pd.notna(row["nutrition"]):
        macros = _parse_nutrition(str(row["nutrition"]))
        if macros:
            parts.append(
                f"Nutrition per serving: {macros['calories']} calories, "
                f"{macros['protein_g']}g protein, "
                f"{macros['carbs_g']}g carbs, "
                f"{macros['total_fat_g']}g fat, "
                f"{macros['sugar_g']}g sugar, "
                f"{macros['sodium_mg']}mg sodium"
            )

    if "ingredients" in row and pd.notna(row["ingredients"]):
        parts.append(f"Ingredients: {row['ingredients']}")

    if "steps" in row and pd.notna(row["steps"]):
        parts.append(f"Directions: {row['steps']}")

    if "description" in row and pd.notna(row["description"]):
        parts.append(f"Description: {row['description']}")

    return "\n".join(parts)


def load_recipe_documents(max_recipes: int = 75) -> list[Document]:
    """Load recipes from CSV and convert each row to a Document.

    Pipeline:
      1. Read CSV with pandas
      2. Drop rows missing name or ingredients
      3. Sample down to max_recipes for manageability
      4. Convert each row to a narrative Document with metadata
      5. Quality-filter out any empty/tiny results
    """
    csv_path = _find_csv(RECIPES_DIR)
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]

    df = df.dropna(subset=["name", "ingredients"])

    if len(df) > max_recipes:
        df = df.sample(n=max_recipes, random_state=42)

    docs: list[Document] = []
    for _, row in df.iterrows():
        narrative = _recipe_to_narrative(row)
        metadata = {
            "source_type": "recipe",
            "name": str(row.get("name", "")),
        }
        docs.append(Document(page_content=narrative, metadata=metadata))

    docs = _quality_filter(docs, "Tier 2")

    print(f"[Tier 2] Recipes: {len(docs)} documents from {csv_path.name}")
    return docs


# ═══════════════════════════════════════════════════════════════════════
# Tier 3 — Fast-food restaurant CSV
# ═══════════════════════════════════════════════════════════════════════

def _restaurant_item_to_narrative(row: pd.Series) -> str:
    """Convert a fast-food menu row into readable text for embedding."""
    restaurant = row.get("restaurant", row.get("company", "Unknown"))
    item = row.get("item", row.get("name", "Unknown"))
    parts = [f"Restaurant: {restaurant}", f"Menu item: {item}"]

    for col, label in [("calories", "Calories"), ("protein", "Protein (g)"),
                        ("total_fat", "Total fat (g)"), ("total_carb", "Carbs (g)"),
                        ("sodium", "Sodium (mg)"), ("fiber", "Fiber (g)"),
                        ("sugar", "Sugar (g)"), ("cholesterol", "Cholesterol (mg)")]:
        if col in row.index and pd.notna(row[col]):
            parts.append(f"{label}: {row[col]}")

    return "\n".join(parts)


def load_restaurant_documents() -> list[Document]:
    """Load fast-food nutrition data and convert each row to a Document.

    Pipeline:
      1. Read CSV with pandas
      2. Convert each row to a narrative Document with metadata
      3. Quality-filter out any empty/tiny results
    """
    csv_path = _find_csv(RESTAURANT_DIR)
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]

    docs: list[Document] = []
    for _, row in df.iterrows():
        narrative = _restaurant_item_to_narrative(row)
        metadata = {
            "source_type": "restaurant",
            "restaurant": str(row.get("restaurant", row.get("company", ""))),
            "item": str(row.get("item", row.get("name", ""))),
        }
        docs.append(Document(page_content=narrative, metadata=metadata))

    docs = _quality_filter(docs, "Tier 3")

    print(f"[Tier 3] Restaurant data: {len(docs)} documents from {csv_path.name}")
    return docs


# ═══════════════════════════════════════════════════════════════════════
# Combined loader — the single entry point
# ═══════════════════════════════════════════════════════════════════════

def load_all_documents() -> list[Document]:
    """Load and merge documents from all three data tiers.

    This is the ONLY function the rest of the app calls. It returns
    one flat list that gets fed directly into the Qdrant collection.
    """
    nutrition_docs = load_nutrition_documents()
    recipe_docs = load_recipe_documents()
    restaurant_docs = load_restaurant_documents()

    all_docs = nutrition_docs + recipe_docs + restaurant_docs
    print(f"\n[All tiers] Total documents ready for ingestion: {len(all_docs)}")
    return all_docs
