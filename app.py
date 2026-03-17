"""Chainlit entry point — boots the app and handles user messages.

Run with:  chainlit run app.py

Two modes:
  - Chat: conversational agent with 7 nutrition tools
  - Dashboard: visual charts of calories, macros, and progress
"""

import os
import logging
from datetime import datetime

import chainlit as cl
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

from macro_mate.data_loader import load_all_documents
from macro_mate.vector_store import create_vector_store
from macro_mate.retrievers import create_ensemble_retriever
from macro_mate.memory import create_checkpointer, create_memory_store
from macro_mate.tools import create_tools
from macro_mate.agent import build_graph

# ── Module-level variables set during startup ─────────────────────────
agent = None
_store = None  # keep a reference for dashboard reads


# ── Authentication ────────────────────────────────────────────────────
# Google OAuth — activates only when credentials are configured.
if os.environ.get("OAUTH_GOOGLE_CLIENT_ID"):
    @cl.oauth_callback
    def oauth_callback(
        provider_id: str,
        token: str,
        raw_user_data: dict,
        default_user: cl.User,
    ) -> cl.User | None:
        return default_user


# Password auth — always available as fallback.
@cl.password_auth_callback
def auth_callback(username: str, password: str) -> cl.User | None:
    demo_pw = os.environ.get("DEMO_PASSWORD", "macromind")
    logger.info(f"Login attempt for user: {username}")
    if password == demo_pw:
        logger.info(f"Login successful: {username}")
        return cl.User(identifier=username)
    logger.warning(f"Login failed for user: {username}")
    return None


# ── Chat Profiles ─────────────────────────────────────────────────────

@cl.set_chat_profiles
async def chat_profiles(current_user: cl.User | None):
    return [
        cl.ChatProfile(
            name="Chat",
            markdown_description="Talk to MacroMind — log meals, ask questions, get insights",
            icon="https://cdn-icons-png.flaticon.com/512/1041/1041916.png",
            default=True,
            starters=[
                cl.Starter(label="Log a Meal", message="I need to log a meal", icon="https://cdn-icons-png.flaticon.com/512/1046/1046857.png"),
                cl.Starter(label="Daily Summary", message="Show my daily summary", icon="https://cdn-icons-png.flaticon.com/512/3596/3596091.png"),
                cl.Starter(label="Set Up Profile", message="Help me set up my profile", icon="https://cdn-icons-png.flaticon.com/512/1077/1077114.png"),
                cl.Starter(label="Analyze Progress", message="Analyze my nutrition progress", icon="https://cdn-icons-png.flaticon.com/512/3281/3281289.png"),
            ],
        ),
        cl.ChatProfile(
            name="Dashboard",
            markdown_description="View your nutrition dashboard with charts and stats",
            icon="https://cdn-icons-png.flaticon.com/512/1828/1828791.png",
            starters=[
                cl.Starter(label="Refresh Dashboard", message="Show my dashboard", icon="https://cdn-icons-png.flaticon.com/512/3596/3596091.png"),
                cl.Starter(label="Switch to Chat", message="Let me talk to MacroMind", icon="https://cdn-icons-png.flaticon.com/512/1041/1041916.png"),
            ],
        ),
    ]


# ── Dashboard rendering ──────────────────────────────────────────────

async def render_dashboard(user_id: str):
    """Build and send plotly charts showing the user's nutrition data."""
    import plotly.graph_objects as go

    if _store is None:
        await cl.Message(content="Dashboard is loading... please wait a moment and try again.").send()
        return

    today = datetime.now().strftime("%Y-%m-%d")

    # ── Read data from store ──────────────────────────────────────
    # Profile + TDEE
    profile_items = list(_store.search((user_id, "profile")))
    profile = {item.key: item.value.get("value", "") for item in profile_items}
    tdee = float(profile.get("tdee", 0)) if "tdee" in profile else 0

    # Today's meals
    all_meals = list(_store.search((user_id, "consumption"), query="meal food", limit=500))
    today_meals = [m for m in all_meals if m.value.get("date") == today]

    total_cal = sum(m.value.get("calories", 0) for m in today_meals)
    total_protein = sum(m.value.get("protein_g", 0) for m in today_meals)
    total_carbs = sum(m.value.get("carbs_g", 0) for m in today_meals)
    total_fat = sum(m.value.get("fat_g", 0) for m in today_meals)

    # Streak
    streak_items = list(_store.search((user_id, "streaks")))
    streak_count = streak_items[0].value.get("count", 0) if streak_items else 0
    streak_best = streak_items[0].value.get("longest", 0) if streak_items else 0

    # ── Build charts ──────────────────────────────────────────────
    elements = []

    # 1. Calorie gauge
    if tdee > 0:
        remaining = max(0, tdee - total_cal)
        pct = min(100, round((total_cal / tdee) * 100))
        cal_fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=round(total_cal),
            title={"text": "Calories Today", "font": {"size": 20}},
            delta={"reference": tdee, "decreasing": {"color": "green"}, "increasing": {"color": "red"}},
            gauge={
                "axis": {"range": [0, tdee], "tickwidth": 1},
                "bar": {"color": "#FF6B35"},
                "steps": [
                    {"range": [0, tdee * 0.5], "color": "#E8F5E9"},
                    {"range": [tdee * 0.5, tdee * 0.8], "color": "#FFF3E0"},
                    {"range": [tdee * 0.8, tdee], "color": "#FFEBEE"},
                ],
                "threshold": {"line": {"color": "red", "width": 3}, "thickness": 0.75, "value": tdee},
            },
        ))
        cal_fig.update_layout(height=300, margin=dict(l=20, r=20, t=60, b=20))
        elements.append(cl.Plotly(name="calorie_gauge", figure=cal_fig, display="inline"))

    # 2. Macro breakdown pie chart
    if total_cal > 0:
        macro_fig = go.Figure(go.Pie(
            labels=["Protein", "Carbs", "Fat"],
            values=[round(total_protein), round(total_carbs), round(total_fat)],
            hole=0.4,
            marker=dict(colors=["#4CAF50", "#2196F3", "#FF9800"]),
            textinfo="label+value",
            texttemplate="%{label}<br>%{value}g",
        ))
        macro_fig.update_layout(
            title_text="Macro Breakdown (grams)", title_x=0.5,
            height=300, margin=dict(l=20, r=20, t=60, b=20),
        )
        elements.append(cl.Plotly(name="macro_pie", figure=macro_fig, display="inline"))

    # 3. Weekly calorie trend (if multi-day data exists)
    from collections import defaultdict
    days = defaultdict(float)
    for m in all_meals:
        d = m.value.get("date", "")
        if d:
            days[d] += m.value.get("calories", 0)

    if len(days) > 1:
        sorted_days = sorted(days.items())[-7:]  # last 7 days
        dates = [d[0] for d in sorted_days]
        cals = [round(d[1]) for d in sorted_days]

        trend_fig = go.Figure()
        trend_fig.add_trace(go.Bar(x=dates, y=cals, name="Calories", marker_color="#FF6B35"))
        if tdee > 0:
            trend_fig.add_hline(y=tdee, line_dash="dash", line_color="red",
                                annotation_text=f"TDEE: {round(tdee)}")
        trend_fig.update_layout(
            title_text="Daily Calories (Last 7 Days)", title_x=0.5,
            xaxis_title="Date", yaxis_title="Calories",
            height=300, margin=dict(l=40, r=20, t=60, b=40),
        )
        elements.append(cl.Plotly(name="weekly_trend", figure=trend_fig, display="inline"))

    # ── Build summary text ────────────────────────────────────────
    streak_text = f"**Streak:** {streak_count} day(s) (Best: {streak_best})" if streak_count > 0 else "**Streak:** Start logging to begin!"

    if not profile:
        profile_text = "*No profile set up yet. Switch to Chat and set your profile!*"
    else:
        profile_lines = []
        if "weight_kg" in profile:
            profile_lines.append(f"Weight: {profile['weight_kg']} kg")
        if "height_cm" in profile:
            profile_lines.append(f"Height: {profile['height_cm']} cm")
        if "tdee" in profile:
            profile_lines.append(f"TDEE: {profile['tdee']} cal/day")
        profile_text = " | ".join(profile_lines) if profile_lines else "*Profile incomplete*"

    today_text = f"**Today:** {round(total_cal)} cal | {round(total_protein)}g protein | {round(total_carbs)}g carbs | {round(total_fat)}g fat"
    if tdee > 0:
        remaining = round(tdee - total_cal)
        today_text += f" | **{remaining} cal remaining**"

    meals_text = f"**Meals logged today:** {len(today_meals)}"

    dashboard_md = (
        f"## MacroMind Dashboard\n\n"
        f"{profile_text}\n\n"
        f"{today_text}\n\n"
        f"{meals_text} | {streak_text}\n\n"
        f"---\n"
    )

    if not elements:
        dashboard_md += "\n*Log some meals to see your charts! Switch to Chat mode to get started.*"

    await cl.Message(content=dashboard_md, elements=elements).send()


# ── Main startup ──────────────────────────────────────────────────────

@cl.on_chat_start
async def start():
    """Runs once when a user opens the chat. Sets up the full pipeline.

    IMPORTANT: We do NOT send any messages here.  Sending a message in
    on_chat_start immediately clears Chainlit's starter buttons, which
    is why they used to flash and disappear.  By staying silent, we let
    chainlit.md serve as the welcome content and the starter buttons
    remain visible until the user clicks one or types a message.
    """
    global agent, _store

    if agent is None:
        # Lazy-init happens once on cold start. We still show a loading
        # message here because the user will otherwise stare at a blank
        # screen for 10-15 seconds. This only fires on the very first
        # request after a deploy — subsequent profile switches skip it.
        status = cl.Message(content="Setting up MacroMind — this takes a moment on first launch...")
        await status.send()

        documents = load_all_documents()
        vector_store = create_vector_store(documents)
        retriever = create_ensemble_retriever(vector_store, documents)
        checkpointer = create_checkpointer()
        _store = create_memory_store()
        tools = create_tools(retriever, _store)
        agent = build_graph(tools, checkpointer=checkpointer, store=_store)

    # Don't send any messages — chainlit.md + starters handle the welcome.
    # Starters persist until the user clicks one or types a message.


@cl.on_message
async def handle_message(message: cl.Message):
    """Runs every time the user sends a message."""
    user = cl.user_session.get("user")
    user_id = user.identifier if user else "default_user"
    profile = cl.user_session.get("chat_profile")

    # ── Dashboard mode ────────────────────────────────────────────
    # Any message in Dashboard mode renders the dashboard, EXCEPT
    # if the user asks to switch to Chat (we guide them to the
    # profile selector instead).
    if profile == "Dashboard":
        lower = message.content.lower()
        if any(kw in lower for kw in ["chat", "talk", "macromind"]):
            await cl.Message(
                content="To talk to MacroMind, switch to the **Chat** "
                        "profile using the selector at the top of the page."
            ).send()
        else:
            await render_dashboard(user_id)
        return

    # ── Chat mode ─────────────────────────────────────────────────
    config = {
        "configurable": {
            "thread_id": cl.context.session.id,
        }
    }

    response = agent.invoke(
        {
            "messages": [HumanMessage(content=message.content)],
            "user_id": user_id,
        },
        config=config,
    )

    ai_message = response["messages"][-1]
    await cl.Message(content=ai_message.content).send()
