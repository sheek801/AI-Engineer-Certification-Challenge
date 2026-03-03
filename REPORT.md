# Macro Mate: Certification Challenge Report

## Task 1: Problem and Audience

### Problem Statement

Nutrition-conscious individuals who live active social lifestyles consistently fail to reach their body composition goals. Not because they lack knowledge about healthy eating, but because no existing tool dynamically adapts a personalized nutrition strategy around the unpredictable realities of eating out, social meals, fluctuating budgets, and weekly schedule changes while tracking the actual impact on their body over time.

### Why This Is a Problem

Every person's nutritional needs are fundamentally personal. Caloric requirements and macro targets depend on height, weight, age, and body composition goals. Someone who is 5'8", 180 lbs, and 26 years old trying to cut to 165 lbs has a completely different daily target than someone who is 6'1", 210 lbs, and 35 trying to maintain. Yet current tools treat nutrition planning as either a static calculation or a passive logging exercise. Apps like MyFitnessPal let users track what they already ate (backward-looking, no strategy), and ChatGPT can generate a meal plan on demand but it resets every conversation, forgets weight trends from last week, doesn't know the user ate out three times already, and cannot adapt mid-week when plans change. Paid macro coaches cost $150+/month and still hand clients a rigid PDF that breaks the first time they deviate. The result is a cycle: users start a plan, real life interrupts, the plan feels broken, and they quit. Not because they lacked discipline, but because the tool couldn't flex with them.

This problem is especially acute for city-dwelling professionals and young adults who genuinely want to get leaner, build better habits, and take control of their nutrition, but whose daily reality includes restaurant dinners with friends, budget-constrained weeks, spontaneous plan changes, and the social dimension of food that rigid meal plans ignore. These users don't need more nutrition information (they already know protein matters and calories determine weight loss). What they need is an intelligent system that takes their biometrics, calculates their actual caloric and macro needs, answers science-backed dietary questions, surfaces relevant recipes and restaurant options, tracks daily intake, and adapts when plans change. That turns nutrition from a willpower test into a strategic, data-informed process.

### Evaluation Questions

These 20 representative queries exercise every tool and data tier in the application:

| # | Tool | Data Tier | Query |
|---|------|-----------|-------|
| 1 | `search_nutrition_knowledge` | Nutrition Science (PDF/TXT) | How much protein should I eat per day if I weigh 180 lbs and lift weights? |
| 2 | `search_nutrition_knowledge` | Nutrition Science (PDF/TXT) | What does the USDA Dietary Guidelines say about added sugars? |
| 3 | `search_nutrition_knowledge` | Nutrition Science (PDF/TXT) | Why do weight loss plateaus happen and how do I break through one? |
| 4 | `search_nutrition_knowledge` | Nutrition Science (PDF/TXT) | What is the Mifflin-St Jeor equation? |
| 5 | `search_nutrition_knowledge` | Nutrition Science (PDF/TXT) | What is the recommended daily fiber intake for adults? |
| 6 | `search_nutrition_knowledge` | Recipes (CSV) | Suggest a high-protein recipe under 500 calories |
| 7 | `search_nutrition_knowledge` | Recipes (CSV) | Find me a chicken recipe with low carbs |
| 8 | `search_nutrition_knowledge` | Recipes (CSV) | What recipes do you have that are under 30 minutes to make? |
| 9 | `search_nutrition_knowledge` | Fast Food (CSV) | What are the macros for a McDonald's Big Mac? |
| 10 | `search_nutrition_knowledge` | Fast Food (CSV) | Compare the calories in a Whopper vs a KFC Famous Bowl |
| 11 | `search_nutrition_knowledge` | Fast Food (CSV) | What's the lowest calorie option at Taco Bell? |
| 12 | `search_web` | Web (Tavily) | What are the health benefits of turmeric? |
| 13 | `search_web` | Web (Tavily) | How much caffeine is in a Starbucks Pumpkin Spice Latte? |
| 14 | `log_consumption` | InMemoryStore | I just had a grilled chicken salad, 350 cal, 40g protein, 10g carbs, 15g fat. Log it. |
| 15 | `log_consumption` | InMemoryStore | Log breakfast: 2 eggs and toast, roughly 300 cal, 20g protein, 25g carbs, 15g fat |
| 16 | `manage_user_profile` | InMemoryStore | Set my profile: 180 lbs, 5'11, 28 years old, male, moderately active |
| 17 | `manage_user_profile` | InMemoryStore | Calculate my TDEE |
| 18 | `calculate_daily_summary` | InMemoryStore | How many calories do I have left today? |
| 19 | `analyze_progress` | InMemoryStore | Analyze my progress so far |
| 20 | `analyze_progress` | InMemoryStore | What patterns do you see in my eating habits? |

## Task 2: Proposed Solution

### Solution Description

Macro Mate is a conversational AI assistant built on a ReAct (Reasoning + Acting) agent pattern using LangGraph's StateGraph. The user interacts through a Chainlit chat interface at localhost:8000. When a message arrives, the agent decides which of its six tools to call based on the user's intent: searching the nutrition knowledge base, searching the web, logging a meal, managing a user profile, calculating a daily summary, or analyzing nutrition progress over time.

The experience feels like texting a knowledgeable nutritionist. The user types a question in natural language, and the agent reasons about which tool to use, executes it, interprets the results, and responds in a conversational tone. Behind the scenes, the agent maintains short-term memory (conversation history within a session) and long-term memory (user profile and meal logs that persist across topics). The system prompt guides the agent to always cite sources, include macro details with recipes, and avoid making up nutritional data.

### Infrastructure Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  USER LAYER                                                         │
│                                                                     │
│  Browser  ───►  Chainlit UI (localhost:8000)                        │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AGENT ORCHESTRATION                                                │
│                                                                     │
│  LangGraph StateGraph (ReAct Loop)                                  │
│  ├── LLM: GPT-4o-mini (ChatOpenAI)                                 │
│  └── ToolNode (6 tools)                                             │
│       ├── search_nutrition_knowledge ──────► Retrieval Layer         │
│       ├── search_web ──────────────────────► Tavily API             │
│       ├── log_consumption ─────────────────► InMemoryStore          │
│       ├── manage_user_profile ─────────────► InMemoryStore          │
│       ├── calculate_daily_summary ─────────► InMemoryStore          │
│       └── analyze_progress ────────────────► InMemoryStore          │
│                                                                     │
│  ┌─ Monitoring: LangSmith (traces every LLM call + tool use)       │
│  └─ Memory: MemorySaver (short-term, per-thread checkpointing)     │
└──────────┬──────────────────────────────┬───────────────────────────┘
           │                              │
           ▼                              ▼
┌─────────────────────────────┐  ┌────────────────────────────────────┐
│  RETRIEVAL LAYER            │  │  MEMORY LAYER                      │
│                             │  │                                    │
│  EnsembleRetriever          │  │  MemorySaver                       │
│  ├── BM25 (weight 0.5)     │  │    Short-term conversation history │
│  └── Dense (weight 0.5)    │  │    Per-thread checkpointing        │
│       │                     │  │                                    │
│  Qdrant Vector Store        │  │  InMemoryStore                     │
│    (in-memory, 1536 dims)   │  │    Long-term user data             │
│       │                     │  │    Semantic index (1536 dims)      │
│  text-embedding-3-small     │  │    Profiles, meals, weight logs    │
└──────────┬──────────────────┘  └────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DATA SOURCES (ingested at startup into single Qdrant collection)   │
│                                                                     │
│  ┌───────────────────┐ ┌──────────────────┐ ┌────────────────────┐  │
│  │ Nutrition Science  │ │ Food.com Recipes │ │ Fast Food Data     │  │
│  │ 6 PDFs/TXTs       │ │ 75 filtered rows │ │ 515 menu items     │  │
│  │ (~697 chunks)      │ │ (narrative docs) │ │ (6 restaurant      │  │
│  │ USDA, Harvard,     │ │ Names, macros,   │ │  chains: MCD, BK,  │  │
│  │ Mayo Clinic, etc.  │ │ ingredients,     │ │  Wendy's, KFC,     │  │
│  │                    │ │ directions       │ │  Taco Bell, Pizza  │  │
│  │                    │ │                  │ │  Hut)              │  │
│  └───────────────────┘ └──────────────────┘ └────────────────────┘  │
│                                                                     │
│  Total: 1,287 documents embedded into one Qdrant collection         │
└─────────────────────────────────────────────────────────────────────┘

External Services:
  • Tavily Web Search: fallback when knowledge base lacks the answer
  • LangSmith: trace-level monitoring of every agent step

Evaluation:
  • RAGAS Framework: 21 synthetic QA pairs, 5 metrics
  • Compared dense-only baseline vs. EnsembleRetriever
```

### Tooling Justifications

- **GPT-4o-mini**: Cost-effective model with strong instruction-following and tool-calling capabilities, well suited for a prototype where API costs need to stay low.
- **LangGraph StateGraph**: Provides explicit control over the ReAct loop (assistant node, tool node, routing), unlike black-box agent wrappers, making the agent's decision process transparent and debuggable.
- **6 Agent Tools**: Each tool handles a distinct user intent (RAG search, web search, meal logging, profile management, daily summary, progress analysis), giving the agent clear boundaries for when to use each.
- **text-embedding-3-small (1536 dims)**: OpenAI's latest small embedding model balances quality and cost for semantic retrieval.
- **Qdrant (in-memory)**: Fast vector similarity search with zero infrastructure overhead; in-memory mode is ideal for prototyping and local deployment.
- **LangSmith**: Provides trace-level observability into every LLM call, tool invocation, and retrieval step, essential for debugging agent behavior in production.
- **RAGAS**: The standard evaluation framework for RAG pipelines, providing automated metrics (faithfulness, context precision, context recall) that quantify retrieval and generation quality.
- **Chainlit**: Native LangGraph integration with a polished chat UI, supports streaming and session management out of the box.
- **Local deployment (Chainlit)**: Meets the rubric requirement for a local endpoint without needing cloud infrastructure.

### RAG and Agent Components

The **RAG component** is the retrieval pipeline: documents from three data tiers (nutrition science PDFs/TXTs, Food.com recipes, fast food CSV) are loaded, chunked (for PDFs/TXTs) or converted to narrative text (for CSVs), embedded with text-embedding-3-small, and stored in a single Qdrant collection. At query time, the EnsembleRetriever combines BM25 keyword matching with dense vector search using reciprocal rank fusion to surface the most relevant documents.

The **Agent component** is the LangGraph StateGraph that orchestrates the ReAct loop. The assistant node calls GPT-4o-mini with the system prompt and conversation history. If the model decides to use a tool, the ToolNode executes it and feeds the result back to the assistant for another reasoning step. This loop continues until the model produces a final response without tool calls. The agent also manages short-term memory (MemorySaver for conversation continuity) and long-term memory (InMemoryStore for user profiles and meal logs). The `analyze_progress` tool closes the memory feedback loop by reading back all stored data (profile, meals, weight history), computing per-day totals and averages, and returning structured context that the LLM then reasons over to identify patterns and generate actionable suggestions.

## Task 3: Data and External APIs

### Chunking Strategy

For Tier 1 (nutrition science PDFs and text files), I use `RecursiveCharacterTextSplitter` with a chunk size of 1000 characters and 200-character overlap. This is the standard chunking approach taught in the bootcamp, and the parameters were chosen because:

- 1000 characters keeps each chunk focused on a single concept while providing enough context for the embedding model to capture meaning.
- 200-character overlap ensures that sentences split at chunk boundaries still appear in at least one complete chunk, preventing information loss at the edges.
- A quality filter removes any chunks shorter than 50 characters (typically page headers, footers, or blank pages from PDF extraction).

For Tier 2 (recipes) and Tier 3 (fast food), no text splitting is needed. Each CSV row is converted into a self-contained narrative document. Recipes include the name, cook time, ingredients, directions, and parsed macro information. Fast food items include the restaurant, menu item name, and all available nutritional columns. This approach preserves the logical integrity of each record.

### Data Sources and External API

**Data sources (RAG):**

- `data/nutrition_science/`: 6 files covering USDA Dietary Guidelines (PDF), Examine.com protein guide (PDF), Harvard protein needs (TXT), Mayo Clinic weight loss plateaus (TXT), Mifflin-St Jeor TDEE equation (TXT), and NASM calorie/macro guide (TXT). These provide the scientific foundation for nutrition advice.
- `data/recipes/recipes_filtered.csv`: 75 pre-filtered recipes from the Food.com dataset (230K+ in the full dataset, available at https://www.kaggle.com/datasets/shuyangli94/food-com-recipes-and-user-interactions). Each row is converted to a narrative document with parsed macro information from the nutrition column.
- `data/restaurant_data/fastfood.csv`: Fast food menu items with calories, protein, fat, carbs, sodium, fiber, sugar, and cholesterol per item.

**External API (Agent):**

- **Tavily Search**: When the knowledge base does not contain the answer (for example, questions about recent nutrition research or a restaurant not in the dataset), the agent falls back to Tavily's web search API. Tavily returns concise, relevant excerpts from the web, which the agent then uses to formulate its response. This ensures the agent can handle questions beyond the scope of the curated dataset.

During usage, the agent first searches the knowledge base using the `search_nutrition_knowledge` tool. If the results are insufficient or the question is about current/trending topics, the agent calls `search_web` to supplement with live web data. The two tools complement each other: the knowledge base provides curated, consistent answers, while web search fills gaps for edge cases.

## Task 4: End-to-End Prototype

The application is deployed to a local endpoint using Chainlit at `http://localhost:8000`. Running `chainlit run app.py` boots the full pipeline:

1. All 1,287 documents are loaded and embedded into the Qdrant in-memory vector store
2. The EnsembleRetriever (BM25 + Dense) is initialized
3. Both memory systems (MemorySaver + InMemoryStore) are created
4. The 6 agent tools are built and bound to the LLM
5. The LangGraph StateGraph is compiled and ready for invocation

The user opens their browser, types a nutrition question, and receives a grounded response within seconds. The agent was tested with questions spanning all six tools: nutrition science queries, recipe lookups, fast food macro checks, meal logging, profile setup, TDEE calculation, daily summaries, and progress analysis.

## Task 5: Baseline Evaluation with RAGAS

### Evaluation Setup

I generated a synthetic test dataset of 21 QA pairs using the RAGAS `TestsetGenerator`, which analyzes the ingested documents and creates questions with reference answers and reference contexts. This dataset was saved to `eval/testset.jsonl` so that both the baseline and advanced evaluations use the exact same questions for a fair comparison.

The baseline uses a dense-only retriever (Qdrant vector store with text-embedding-3-small, k=5). Each question is run through the retriever to get context, then through GPT-4o-mini (temperature=0) to generate a response. RAGAS then scores the responses against the reference answers and contexts.

### Baseline Results (Dense Retriever)

| Metric | Score |
|---|---|
| Faithfulness | 0.9003 |
| Context Precision | 0.8546 |
| Context Recall | 0.8365 |
| Factual Correctness | 0.4533 |
| Response Relevancy | 0.9052 |

### Conclusions

**Faithfulness (0.90)**: The pipeline produces highly grounded answers. 90% of claims in generated responses can be traced back to the retrieved context. The LLM is not hallucinating and is faithfully using the provided documents.

**Response Relevancy (0.91)**: Responses directly address the question asked. The system prompt and tool design effectively guide the LLM to produce focused, on-topic answers.

**Context Precision (0.85)**: Most retrieved documents are actually useful for answering the question. Only about 15% of retrieved chunks are noise, showing that semantic matching works well for this domain.

**Context Recall (0.84)**: Approximately 16% of the information needed to fully answer questions is not being retrieved. Dense retrieval can miss documents that match by exact keywords but differ in semantic phrasing. For example, a query about "Mifflin-St Jeor equation" might not surface all relevant chunks if the embedding does not capture that specific term well.

**Factual Correctness (0.45)**: The weakest metric, but context matters. RAGAS auto-generates terse, one-line reference answers, while GPT-4o-mini produces detailed multi-paragraph responses. The F1 token overlap between a brief reference and a verbose answer will naturally be low even when the content is correct. This metric reflects answer verbosity versus reference brevity more than actual factual errors.

**Overall**: The dense-only retriever provides a solid baseline with strong faithfulness and relevance. The main opportunity for improvement is context recall, which could benefit from a retrieval method that combines keyword matching with semantic search.

## Task 6: Advanced Retriever

### Chosen Technique

**EnsembleRetriever** combining BM25 (sparse keyword search) with Qdrant dense vector retrieval, weighted 0.5/0.5 using reciprocal rank fusion.

I chose this technique because the dense-only baseline showed a gap in context recall (0.84). BM25 excels at exact term matching for specific nutrient names, recipe titles, and equation names like "Mifflin-St Jeor" that semantic embeddings can struggle with. Combining both methods through reciprocal rank fusion captures documents that match by meaning (dense) and documents that match by exact wording (BM25), which is particularly valuable in the nutrition domain where precise quantities and proper nouns are common.

### Results Comparison

| Metric | Dense (Baseline) | Ensemble (Improved) | Change |
|---|---|---|---|
| Faithfulness | 0.9003 | 0.8775 | -0.0228 |
| Context Precision | 0.8546 | 0.7955 | -0.0591 |
| Context Recall | 0.8365 | 0.9159 | +0.0794 |
| Factual Correctness | 0.4533 | 0.5524 | +0.0991 |
| Response Relevancy | 0.9052 | 0.9067 | +0.0015 |

### Analysis

The ensemble retriever improved context recall from 0.84 to 0.92 (+8 percentage points). This confirms the hypothesis: BM25 catches exact-match documents that semantic search alone misses. The improvement in factual correctness (+10 percentage points) follows directly, because better context recall means the LLM has more complete information to work with.

The trade-offs are expected. Context precision dropped slightly (-0.06) because the ensemble casts a wider net, surfacing some additional documents that are less precisely relevant. Faithfulness decreased marginally (-0.02), still at 88%, because the LLM has more context to potentially misinterpret. Response relevancy remained unchanged.

For a nutrition chatbot where completeness and accuracy of information matter for user safety, higher recall is the more important metric to optimize. The small precision trade-off is worthwhile.

## Task 7: Next Steps

I plan to keep the EnsembleRetriever (BM25 + Dense) for Demo Day rather than reverting to dense-only retrieval. The evaluation data shows a clear improvement in the metrics that matter most for this use case: context recall jumped from 84% to 92%, meaning the system finds more of the relevant information, and factual correctness improved by 10 percentage points as a direct result.

The small decrease in context precision (85% to 80%) is an acceptable trade-off. In a nutrition application, missing relevant information is more harmful than retrieving a few extra documents. A user asking about daily protein needs should get all the relevant guidance from the knowledge base, even if one or two of the five retrieved chunks are tangential.

For further improvement, potential next steps include:

- Adding Cohere reranking on top of the ensemble to recover precision without sacrificing recall
- Expanding the recipe dataset beyond 75 samples for broader coverage
- Adding a feedback loop where users can rate answers to build a human-evaluated test set
- Deploying to a public endpoint via Render for broader access
- Integrating with a persistent database (PostgreSQL or Qdrant Cloud) so user profiles and meal logs survive restarts
