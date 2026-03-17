"""Chainlit entry point — boots the app and handles user messages.

Run with:  chainlit run app.py

Three flows:
  - Onboarding: new users set up their profile (weight, height, age, sex, activity)
  - Chat: conversational agent with 7 nutrition tools
  - Dashboard: visual charts of calories, macros, and progress
"""

import os
import logging
from datetime import datetime

import chainlit as cl
from chainlit.input_widget import Select, NumberInput
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

from macro_mate.data_loader import load_all_documents
from macro_mate.vector_store import create_vector_store
from macro_mate.retrievers import create_ensemble_retriever
from macro_mate.memory import create_checkpointer, create_memory_store
from macro_mate.tools import create_tools
from macro_mate.agent import build_graph
from macro_mate.utils import calculate_tdee

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
        ),
        cl.ChatProfile(
            name="Dashboard",
            markdown_description="View your nutrition dashboard with charts and stats",
            icon="https://cdn-icons-png.flaticon.com/512/1828/1828791.png",
        ),
    ]


# ── Starters (standalone, profile-aware) ──────────────────────────────

@cl.set_starters
async def starters(current_user: cl.User | None, language: str | None = None):
    try:
        profile = cl.user_session.get("chat_profile")
    except Exception:
        profile = "Chat"
    if profile == "Dashboard":
        return []
    return [
        cl.Starter(
            label="Log a Meal",
            message="I need to log a meal",
            icon="https://cdn-icons-png.flaticon.com/512/1046/1046857.png",
        ),
        cl.Starter(
            label="Daily Summary",
            message="Show my daily summary",
            icon="https://cdn-icons-png.flaticon.com/512/3596/3596091.png",
        ),
        cl.Starter(
            label="Update Profile",
            message="Help me update my profile",
            icon="https://cdn-icons-png.flaticon.com/512/1077/1077114.png",
        ),
        cl.Starter(
            label="Analyze Progress",
            message="Analyze my nutrition progress",
            icon="https://cdn-icons-png.flaticon.com/512/3281/3281289.png",
        ),
    ]


# ── Onboarding ────────────────────────────────────────────────────────

def _check_profile_complete(user_id: str) -> bool:
    """Return True if the user has all required profile fields."""
    if _store is None:
        return False
    profile_items = list(_store.search((user_id, "profile")))
    profile = {item.key: item.value.get("value", "") for item in profile_items}
    required = {"weight_kg", "height_cm", "age", "sex", "activity_level"}
    return all(f in profile for f in required)


async def _show_onboarding_settings():
    """Show the profile setup form as a ChatSettings panel."""
    settings = cl.ChatSettings([
        Select(
            id="units",
            label="Units",
            values=["Imperial (lbs, in)", "Metric (kg, cm)"],
            initial_index=0,
            description="Choose your preferred measurement system",
        ),
        NumberInput(
            id="weight",
            label="Weight",
            placeholder="e.g. 165 (lbs) or 75 (kg)",
            description="Your current body weight",
        ),
        NumberInput(
            id="height",
            label="Height",
            placeholder="e.g. 70 (inches) or 178 (cm)",
            description="Your height — for inches: 5'10\" = 70",
        ),
        NumberInput(
            id="age",
            label="Age",
            placeholder="e.g. 30",
            description="Your age in years",
        ),
        Select(
            id="sex",
            label="Biological Sex",
            values=["Male", "Female"],
            initial_index=0,
            description="Used for calorie calculation (Mifflin-St Jeor)",
        ),
        Select(
            id="activity",
            label="Activity Level",
            values=[
                "Sedentary (desk job, little exercise)",
                "Light (exercise 1-3 days/week)",
                "Moderate (exercise 3-5 days/week)",
                "Active (exercise 6-7 days/week)",
                "Very Active (intense daily training)",
            ],
            initial_index=2,
            description="How active are you on a typical week?",
        ),
    ])
    await settings.send()


def _process_onboarding(settings: dict, user_id: str) -> str | None:
    """Validate settings, convert units, store profile, return error or None."""
    units = settings.get("units", "Imperial (lbs, in)")
    is_imperial = "Imperial" in units

    # ── Validate ──────────────────────────────────────────────────
    weight_raw = settings.get("weight")
    height_raw = settings.get("height")
    age_raw = settings.get("age")

    if not weight_raw or not height_raw or not age_raw:
        return "Please fill in **all** fields (weight, height, age) then click Confirm again."

    try:
        weight_val = float(weight_raw)
        height_val = float(height_raw)
        age_val = int(float(age_raw))
    except (ValueError, TypeError):
        return "Weight, height, and age must be numbers. Please correct and try again."

    if weight_val <= 0 or height_val <= 0 or age_val <= 0:
        return "Values must be positive numbers. Please correct and try again."

    # ── Convert to metric ─────────────────────────────────────────
    if is_imperial:
        weight_kg = round(weight_val / 2.20462, 1)   # lbs → kg
        height_cm = round(height_val * 2.54, 1)       # inches → cm
    else:
        weight_kg = round(weight_val, 1)
        height_cm = round(height_val, 1)

    sex_raw = settings.get("sex", "Male")
    sex = sex_raw.lower()

    activity_raw = settings.get("activity", "Moderate (exercise 3-5 days/week)")
    activity_map = {
        "Sedentary": "sedentary",
        "Light": "light",
        "Moderate": "moderate",
        "Active": "active",
        "Very Active": "very_active",
    }
    activity = "moderate"
    for label, key in activity_map.items():
        if activity_raw.startswith(label):
            activity = key
            break

    # ── Calculate TDEE ────────────────────────────────────────────
    bmr, tdee = calculate_tdee(weight_kg, height_cm, age_val, sex, activity)

    # ── Store in PersistentStore ──────────────────────────────────
    ns = (user_id, "profile")
    _store.put(ns, "weight_kg", {"value": str(weight_kg)})
    _store.put(ns, "height_cm", {"value": str(height_cm)})
    _store.put(ns, "age", {"value": str(age_val)})
    _store.put(ns, "sex", {"value": sex})
    _store.put(ns, "activity_level", {"value": activity})
    _store.put(ns, "tdee", {"value": str(round(tdee))})
    # Store unit preference for display
    _store.put(ns, "units", {"value": "imperial" if is_imperial else "metric"})

    # ── Build confirmation ────────────────────────────────────────
    if is_imperial:
        w_display = f"{weight_val} lbs ({weight_kg} kg)"
        h_display = f"{height_val} in ({height_cm} cm)"
    else:
        w_display = f"{weight_kg} kg"
        h_display = f"{height_cm} cm"

    cl.user_session.set("onboarding_complete", True)
    return None  # success — no message needed


@cl.on_settings_update
async def on_settings_update(settings: dict):
    """Called when the user submits the profile settings form.

    Saves silently so starter buttons are NOT cleared.
    """
    user = cl.user_session.get("user")
    user_id = user.identifier if user else "default_user"

    if _store is None:
        return

    result = _process_onboarding(settings, user_id)
    if result is not None:
        # Validation error — must notify the user
        await cl.Message(content=result).send()


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
        dashboard_md += "\n*Log some meals to see your charts! Switch to Chat mode to get started.*\n"

    dashboard_md += "\n---\n*Switch to **Chat** using the profile selector at the top to log meals or ask questions.*"

    await cl.Message(content=dashboard_md, elements=elements).send()


# ── Main startup ──────────────────────────────────────────────────────

async def _ensure_agent():
    """Lazy-init the agent pipeline. No messages sent — safe for starters."""
    global agent, _store
    if agent is not None:
        return
    documents = load_all_documents()
    vector_store = create_vector_store(documents)
    retriever = create_ensemble_retriever(vector_store, documents)
    checkpointer = create_checkpointer()
    _store = create_memory_store()
    tools = create_tools(retriever, _store)
    agent = build_graph(tools, checkpointer=checkpointer, store=_store)


@cl.on_chat_start
async def start():
    """Runs once when a user opens the chat or switches profiles.

    CRITICAL: Never send cl.Message here — it clears starter buttons.
    Agent initialization is deferred to first message via _ensure_agent().
    """
    # Silently init the agent (no message sent → starters persist)
    await _ensure_agent()

    user = cl.user_session.get("user")
    user_id = user.identifier if user else "default_user"
    chat_profile = cl.user_session.get("chat_profile")

    # ── Dashboard mode: render immediately, no chat ────────────────
    if chat_profile == "Dashboard":
        await render_dashboard(user_id)
        return

    # ── Chat mode ──────────────────────────────────────────────────
    # Register the settings form so users can set/update their
    # profile via the gear icon.  chainlit.md serves as welcome.
    await _show_onboarding_settings()


@cl.on_message
async def handle_message(message: cl.Message):
    """Runs every time the user sends a message."""
    user = cl.user_session.get("user")
    user_id = user.identifier if user else "default_user"
    profile = cl.user_session.get("chat_profile")

    # ── Dashboard mode ────────────────────────────────────────────
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
