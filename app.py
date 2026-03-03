"""Chainlit entry point — boots the app and handles user messages.

Run with:  chainlit run app.py

Startup sequence:
  1. Load all documents (PDFs, text files, CSVs)
  2. Create Qdrant vector store and embed documents
  3. Build hybrid retriever (BM25 + dense)
  4. Create memory (checkpointer + store)
  5. Create tools and build the LangGraph agent
  6. Ready — Chainlit serves the chat UI at http://localhost:8000
"""

import chainlit as cl
from langchain_core.messages import HumanMessage

from macro_mate.data_loader import load_all_documents
from macro_mate.vector_store import create_vector_store
from macro_mate.retrievers import create_ensemble_retriever
from macro_mate.memory import create_checkpointer, create_memory_store
from macro_mate.tools import create_tools
from macro_mate.agent import build_graph

# ── Module-level variables set during startup ─────────────────────────
agent = None


@cl.on_chat_start
async def start():
    """Runs once when a user opens the chat. Sets up the full pipeline."""
    global agent

    # Only initialize once — if a second user connects or page refreshes,
    # reuse the existing agent but still show the welcome message.
    if agent is None:
        status = cl.Message(content="Setting up Macro Mate — this takes a moment on first launch...")
        await status.send()

        # Step 1: Load all documents from the three data tiers
        documents = load_all_documents()

        # Step 2: Embed documents into Qdrant
        vector_store = create_vector_store(documents)

        # Step 3: Build hybrid retriever
        retriever = create_ensemble_retriever(vector_store, documents)

        # Step 4: Create memory systems
        checkpointer = create_checkpointer()
        store = create_memory_store()

        # Step 5: Create tools and build the agent graph
        tools = create_tools(retriever, store)
        agent = build_graph(tools, checkpointer=checkpointer, store=store)

    # Always show the welcome message — even on refresh
    welcome = (
        "## 👋 Welcome to Macro Mate!\n\n"
        "I'm your nutrition intelligence assistant. Here's what I can do:\n\n"
        "| Capability | Example |\n"
        "|---|---|\n"
        "| 🔬 **Nutrition Science** | *What is the Mifflin-St Jeor equation?* |\n"
        "| 🍳 **Recipe Search** | *Suggest a high-protein recipe under 500 calories* |\n"
        "| 🍔 **Fast Food Macros** | *What are the macros for a McDonald's Big Mac?* |\n"
        "| 🌐 **Web Search** | *What are the health benefits of turmeric?* |\n"
        "| 📝 **Meal Logging** | *I had a chicken salad with 350 cal for lunch. Log it.* |\n"
        "| 👤 **Profile & TDEE** | *Set my profile: 180 lbs, 5'11, 28, male, active* |\n"
        "| 📊 **Daily Summary** | *How many calories do I have left today?* |\n"
        "| 📈 **Progress Analysis** | *Analyze my progress* |\n\n"
        "**Getting started:** Try setting up your profile first, then log a meal "
        "and ask for your daily summary to see it all come together!"
    )
    await cl.Message(content=welcome).send()


@cl.on_message
async def handle_message(message: cl.Message):
    """Runs every time the user sends a message."""

    
    config = {
        "configurable": {
            "thread_id": cl.context.session.id,
        }
    }

    response = agent.invoke(
        {
            "messages": [HumanMessage(content=message.content)],
            "user_id": "default_user",
        },
        config=config,
    )

    # The last message in the state is the agent's final response
    ai_message = response["messages"][-1]
    await cl.Message(content=ai_message.content).send()
