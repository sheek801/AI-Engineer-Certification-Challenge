"""Agent — the LangGraph StateGraph that orchestrates everything.

This is where all the pieces come together:
  - State defines what data flows through the graph
  - The assistant node calls the LLM with tools bound
  - The tools node executes whichever tool the LLM chose
  - The routing function decides: call another tool, or respond?

The graph:
    START → assistant → should_continue? ─── has tool_calls ──→ tools ─┐
                ↑                                                       │
                └───────────────────────────────────────────────────────┘
                         ↓ (no tool_calls)
                        END
"""

from typing import Annotated, Literal
from typing_extensions import TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from macro_mate.config import LLM_MODEL
from macro_mate.prompts import SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════════════════
# State
# ═══════════════════════════════════════════════════════════════════════

class MacroMateState(TypedDict):
    """The data that flows through every node in the graph.

    messages: Conversation history. add_messages makes LangGraph APPEND
              new messages rather than replacing the list.
    user_id:  Identifies the user for profile/consumption lookups.
    """
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str


# ═══════════════════════════════════════════════════════════════════════
# Graph builder
# ═══════════════════════════════════════════════════════════════════════

def build_graph(tools: list, checkpointer=None, store=None):
    """Construct and compile the Macro Mate agent graph.

    Args:
        tools: The list of 6 tools from tools.py.
        checkpointer: MemorySaver for short-term memory.
        store: InMemoryStore for long-term memory.

    Returns:
        A compiled LangGraph ready to .invoke().
    """

    # STEP 1 — Create LLM with tools bound.
    # bind_tools() serializes each tool's name, docstring, and parameter
    # schema so the LLM can generate tool_calls in its response.
    llm = ChatOpenAI(model=LLM_MODEL, temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    # STEP 2 — The assistant node: prepend system prompt, call LLM.
    # This runs every time it's the LLM's "turn" in the loop.
    # It returns {"messages": [response]} which add_messages appends
    # to the existing conversation history in the state.
    def assistant_node(state: MacroMateState):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    # STEP 3 — Routing: check if the LLM wants to call a tool.
    # If the response has tool_calls → route to "tools" node.
    # If not → the LLM is done reasoning, route to END.
    def should_continue(state: MacroMateState) -> Literal["tools", "end"]:
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "end"

    # STEP 4 — Wire the graph: two nodes, three edges.
    graph = StateGraph(MacroMateState)
    graph.add_node("assistant", assistant_node)
    graph.add_node("tools", ToolNode(tools))

    graph.add_edge(START, "assistant")
    graph.add_conditional_edges(
        "assistant",
        should_continue,
        {"tools": "tools", "end": END},
    )
    graph.add_edge("tools", "assistant")

    # STEP 5 — Compile with both memory systems.
    # checkpointer = MemorySaver (conversation history per thread)
    # store = InMemoryStore (user profiles, meal logs across threads)
    return graph.compile(checkpointer=checkpointer, store=store)
