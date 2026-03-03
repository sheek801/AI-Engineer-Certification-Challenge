# Macro Mate: Nutrition Intelligence Chatbot

An Agentic RAG application that helps users track nutrition, explore recipes, look up restaurant macros, and receive personalized dietary guidance. Built for the AI Maker Space AI Engineering Certification Challenge (AIE9, Cohort 9).

## Demo Video

[Loom Video Link](TODO)

## Project Overview

Macro Mate is a conversational nutrition assistant powered by a LangGraph ReAct agent. It combines a curated knowledge base of nutrition science documents, 75 recipes from Food.com, and 515 fast food menu items into a single retrieval pipeline. Users can ask nutrition questions, get recipe suggestions with macro breakdowns, log meals, set up biometric profiles, and calculate their Total Daily Energy Expenditure (TDEE).

The retriever uses an EnsembleRetriever that fuses BM25 keyword search with dense vector retrieval through reciprocal rank fusion, outperforming a dense-only baseline on context recall (+8%) and factual correctness (+10%) as measured by the RAGAS evaluation framework.

## Tech Stack

| Component | Technology |
|---|---|
| LLM | GPT-4o-mini |
| Embeddings | text-embedding-3-small (1536 dims) |
| Orchestration | LangGraph StateGraph |
| Vector Database | Qdrant (in-memory) |
| Retrieval | EnsembleRetriever (BM25 + Dense) |
| Short-term Memory | MemorySaver (per-thread checkpointing) |
| Long-term Memory | InMemoryStore (semantic index for user data) |
| Web Search | Tavily |
| UI | Chainlit |
| Monitoring | LangSmith |
| Evaluation | RAGAS |

## Project Structure

```
macro_mate/
+-- app.py
+-- pyproject.toml
+-- .env.example
+-- REPORT.md
+-- data/
|   +-- nutrition_science/          # 6 PDFs and text files
|   +-- recipes/                    # Food.com recipes_filtered.csv (75 recipes)
|   +-- restaurant_data/            # fastfood.csv
+-- eval/
|   +-- testset.jsonl               # 21 synthetic QA pairs (RAGAS)
|   +-- dense_results.csv           # Per-question dense evaluation scores
|   +-- ensemble_results.csv        # Per-question ensemble evaluation scores
+-- src/macro_mate/
    +-- __init__.py
    +-- config.py
    +-- data_loader.py
    +-- vector_store.py
    +-- retrievers.py
    +-- memory.py
    +-- tools.py
    +-- prompts.py
    +-- agent.py
    +-- eval_dataset.py
    +-- evaluate.py
```

## Data Sources

- **Nutrition Science**: 6 PDFs and text files covering USDA Dietary Guidelines, protein research, TDEE calculations, and plateau management
- **Recipes**: 75 recipes pre-filtered from the [Food.com Recipes and Interactions dataset](https://www.kaggle.com/datasets/shuyangli94/food-com-recipes-and-user-interactions) (230K+ recipes in the full dataset)
- **Fast Food**: 515 menu items from the [Fast Food Nutrition dataset](https://www.kaggle.com/datasets/ulrikthygepedersen/fastfood-nutrition) covering McDonald's, Burger King, Wendy's, KFC, Taco Bell, and Pizza Hut

## Setup Instructions

### Prerequisites

- Python 3.11 or 3.13 (Python 3.14 is not supported by Chainlit)
- API keys for OpenAI, Tavily, and LangSmith

### Installation

```bash
git clone https://github.com/sheek801/AI-Engineer-Certification-Challenge.git
cd AI-Engineer-Certification-Challenge

python3.13 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

### Configuration

Copy the example env file and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
LANGSMITH_API_KEY=lsv2-...
```

### Running the Application

```bash
chainlit run app.py
```

The chat interface will be available at `http://localhost:8000`.

### Running Evaluation

Evaluation dependencies (RAGAS) are included when you install with `.[dev]` above. To run:

```bash
# Generate the synthetic test dataset (one time)
python -m macro_mate.eval_dataset

# Run baseline evaluation (dense retriever)
python -m macro_mate.evaluate --mode dense

# Run advanced evaluation (ensemble retriever)
python -m macro_mate.evaluate --mode ensemble
```

Results are saved to the `eval/` directory.

## Evaluation Results

| Metric | Dense (Baseline) | Ensemble (Improved) | Change |
|---|---|---|---|
| Faithfulness | 0.9003 | 0.8775 | -0.0228 |
| Context Precision | 0.8546 | 0.7955 | -0.0591 |
| Context Recall | 0.8365 | 0.9159 | +0.0794 |
| Factual Correctness | 0.4533 | 0.5524 | +0.0991 |
| Response Relevancy | 0.9052 | 0.9067 | +0.0015 |

The EnsembleRetriever delivers improved context recall and factual correctness at the cost of a small precision trade-off, which is a worthwhile exchange for a nutrition application where completeness matters.

## Sample Queries

Try these queries to explore the full range of Macro Mate's capabilities:

```
# Nutrition science (retrieves from PDFs/TXTs)
How much protein should I eat per day if I weigh 180 pounds and lift weights?
What is the Mifflin-St Jeor equation?

# Recipe search (retrieves from Food.com dataset)
Suggest a high-protein recipe under 500 calories
Find me a chicken recipe with low carbs

# Fast food lookup (retrieves from restaurant dataset)
What are the macros for a McDonald's Big Mac?
What's the lowest calorie option at Taco Bell?

# Web search fallback (Tavily)
What are the health benefits of turmeric?

# Meal logging + profile + daily summary
Set my profile: 180 lbs, 5'11, 28 years old, male, moderately active
Calculate my TDEE
I just had a grilled chicken salad with 350 calories, 40g protein, 10g carbs, 15g fat for lunch. Log it.
How many calories do I have left today?

# Progress analysis (reads back from long-term memory)
Analyze my progress so far
```
