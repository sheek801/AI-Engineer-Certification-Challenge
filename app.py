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
            icon="https://cdn-icons-png.flaticon.com/512/1828/1828765.png",
        ),
    ]


# ── Starters disabled — chat loads directly ───────────────────────────


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

    New users (onboarding): show confirmation (starters already cleared).
    Returning users: save silently so starters are NOT cleared.
    """
    user = cl.user_session.get("user")
    user_id = user.identifier if user else "default_user"

    if _store is None:
        return

    result = _process_onboarding(settings, user_id)
    if result is not None:
        # Validation error — must notify the user
        await cl.Message(content=result).send()
    elif cl.user_session.get("onboarding_welcome_shown"):
        # New user just finished onboarding — show confirmation
        await cl.Message(
            content=(
                "**Profile saved!** Your daily calorie target has been calculated.\n\n"
                "Start a **New Chat** (pencil icon at top left) to see your "
                "quick action buttons, or just type a message to get started!"
            )
        ).send()
    # Returning users updating profile → save silently, starters preserved


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

    # -- Shared iOS dark theme constants --
    _BG = "#1C1C1E"
    _CARD = "#2C2C2E"
    _GRAY = "#8E8E93"
    _CORAL = "#FF6B6B"
    _TEAL = "#4ECDC4"
    _SKY = "#45B7D1"
    _FONT = '"Inter", system-ui, -apple-system, sans-serif'

    # 1. Calorie gauge
    if tdee > 0:
        remaining = max(0, tdee - total_cal)
        pct = min(100, round((total_cal / tdee) * 100))
        cal_fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=round(total_cal),
            title={"text": "Calories Today", "font": {"size": 20, "color": "white", "family": _FONT}},
            number={"font": {"size": 42, "color": "white", "family": _FONT}},
            delta={
                "reference": tdee,
                "decreasing": {"color": _TEAL},
                "increasing": {"color": _CORAL},
                "font": {"size": 16, "family": _FONT},
            },
            gauge={
                "axis": {"range": [0, tdee], "tickwidth": 0, "tickcolor": _BG, "tickfont": {"color": _GRAY, "size": 10}},
                "bar": {"color": _TEAL, "thickness": 0.8},
                "bgcolor": _CARD,
                "borderwidth": 0,
                "steps": [
                    {"range": [0, tdee * 0.5], "color": "#2C3E2C"},
                    {"range": [tdee * 0.5, tdee * 0.8], "color": "#3E3C2C"},
                    {"range": [tdee * 0.8, tdee], "color": "#3E2C2C"},
                ],
                "threshold": {"line": {"color": _CORAL, "width": 2}, "thickness": 0.8, "value": tdee},
            },
        ))
        cal_fig.update_layout(
            height=300, margin=dict(l=20, r=20, t=60, b=20),
            paper_bgcolor=_BG, plot_bgcolor=_BG,
            font=dict(family=_FONT, color="white"),
        )
        elements.append(cl.Plotly(name="calorie_gauge", figure=cal_fig, display="inline"))

    # 2. Macro breakdown pie chart
    if total_cal > 0:
        macro_fig = go.Figure(go.Pie(
            labels=["Protein", "Carbs", "Fat"],
            values=[round(total_protein), round(total_carbs), round(total_fat)],
            hole=0.55,
            marker=dict(
                colors=[_TEAL, _SKY, _CORAL],
                line=dict(color=_BG, width=2),
            ),
            textinfo="label+value",
            texttemplate="%{label}<br>%{value}g",
            textfont=dict(color="white", size=13, family=_FONT),
        ))
        macro_fig.update_layout(
            title_text="Macro Breakdown (grams)",
            title_x=0.5,
            title_font=dict(color="white", size=16, family=_FONT),
            height=300, margin=dict(l=20, r=20, t=60, b=20),
            paper_bgcolor=_BG, plot_bgcolor=_BG,
            font=dict(family=_FONT, color="white"),
            legend=dict(font=dict(color=_GRAY, size=12)),
            showlegend=True,
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
        trend_fig.add_trace(go.Bar(
            x=dates, y=cals, name="Calories",
            marker_color=_SKY,
            marker_line_width=0,
        ))
        if tdee > 0:
            trend_fig.add_hline(
                y=tdee, line_dash="dot", line_color=_CORAL, line_width=2,
                annotation_text=f"TDEE: {round(tdee)}",
                annotation_font=dict(color=_CORAL, size=12, family=_FONT),
            )
        trend_fig.update_layout(
            title_text="Daily Calories (Last 7 Days)",
            title_x=0.5,
            title_font=dict(color="white", size=16, family=_FONT),
            yaxis_title="Calories",
            yaxis=dict(
                titlefont=dict(color=_GRAY, size=12),
                tickfont=dict(color=_GRAY, size=10),
                gridcolor="#3A3A3C", gridwidth=0.5,
                zeroline=False,
            ),
            xaxis=dict(
                tickfont=dict(color=_GRAY, size=10),
                showgrid=False,
            ),
            height=300, margin=dict(l=40, r=20, t=60, b=40),
            paper_bgcolor=_BG, plot_bgcolor=_BG,
            font=dict(family=_FONT, color="white"),
            bargap=0.3,
        )
        elements.append(cl.Plotly(name="weekly_trend", figure=trend_fig, display="inline"))

    # 4. Protein trend (line chart — last 7 days)
    protein_by_day = defaultdict(float)
    for m in all_meals:
        d = m.value.get("date", "")
        if d:
            protein_by_day[d] += m.value.get("protein_g", 0)

    if len(protein_by_day) > 1:
        sorted_pdays = sorted(protein_by_day.items())[-7:]
        p_dates = [d[0] for d in sorted_pdays]
        p_vals = [round(d[1]) for d in sorted_pdays]

        # Protein target: 0.8g per lb bodyweight (or 1.8g per kg)
        protein_target = 0
        if "weight_kg" in profile:
            protein_target = round(float(profile["weight_kg"]) * 1.8)

        pro_fig = go.Figure()
        pro_fig.add_trace(go.Scatter(
            x=p_dates, y=p_vals, mode="lines+markers",
            name="Protein",
            line=dict(color=_TEAL, width=3),
            marker=dict(size=8, color=_TEAL),
        ))
        if protein_target > 0:
            pro_fig.add_hline(
                y=protein_target, line_dash="dot", line_color=_CORAL, line_width=2,
                annotation_text=f"Target: {protein_target}g",
                annotation_font=dict(color=_CORAL, size=11, family=_FONT),
            )
        pro_fig.update_layout(
            title_text="Daily Protein (Last 7 Days)",
            title_x=0.5,
            title_font=dict(color="white", size=16, family=_FONT),
            yaxis_title="Protein (g)",
            yaxis=dict(
                titlefont=dict(color=_GRAY, size=12),
                tickfont=dict(color=_GRAY, size=10),
                gridcolor="#3A3A3C", gridwidth=0.5,
                zeroline=False,
            ),
            xaxis=dict(tickfont=dict(color=_GRAY, size=10), showgrid=False),
            height=280, margin=dict(l=40, r=20, t=60, b=40),
            paper_bgcolor=_BG, plot_bgcolor=_BG,
            font=dict(family=_FONT, color="white"),
            showlegend=False,
        )
        elements.append(cl.Plotly(name="protein_trend", figure=pro_fig, display="inline"))

    # 5. Meal frequency by type (horizontal bar — this week)
    meal_type_counts = defaultdict(int)
    for m in all_meals:
        mt = m.value.get("meal_type", "snack")
        meal_type_counts[mt] += 1

    if meal_type_counts:
        ordered_types = ["breakfast", "lunch", "dinner", "snack"]
        type_labels = [t.capitalize() for t in ordered_types]
        type_counts = [meal_type_counts.get(t, 0) for t in ordered_types]
        type_colors = [_TEAL, _SKY, _CORAL, _GRAY]

        freq_fig = go.Figure(go.Bar(
            y=type_labels, x=type_counts,
            orientation="h",
            marker=dict(color=type_colors, line_width=0),
            text=type_counts, textposition="auto",
            textfont=dict(color="white", size=13, family=_FONT),
        ))
        freq_fig.update_layout(
            title_text="Meals Logged by Type",
            title_x=0.5,
            title_font=dict(color="white", size=16, family=_FONT),
            xaxis=dict(
                tickfont=dict(color=_GRAY, size=10),
                gridcolor="#3A3A3C", gridwidth=0.5,
                zeroline=False,
            ),
            yaxis=dict(tickfont=dict(color="white", size=13), autorange="reversed"),
            height=250, margin=dict(l=80, r=20, t=60, b=20),
            paper_bgcolor=_BG, plot_bgcolor=_BG,
            font=dict(family=_FONT, color="white"),
            bargap=0.35,
        )
        elements.append(cl.Plotly(name="meal_frequency", figure=freq_fig, display="inline"))

    # ── Build summary text ────────────────────────────────────────
    streak_text = f"**Streak:** {streak_count} day(s) (Best: {streak_best})" if streak_count > 0 else "**Streak:** Start logging to begin!"

    if not profile:
        profile_text = "*No profile set up yet. Switch to Chat and set your profile!*"
    else:
        profile_lines = []
        units = profile.get("units", "metric")
        if "weight_kg" in profile:
            w = float(profile["weight_kg"])
            if units == "imperial":
                profile_lines.append(f"Weight: {round(w * 2.20462)} lbs")
            else:
                profile_lines.append(f"Weight: {w} kg")
        if "height_cm" in profile:
            h = float(profile["height_cm"])
            if units == "imperial":
                total_in = round(h / 2.54)
                feet, inches = divmod(total_in, 12)
                profile_lines.append(f"Height: {feet}'{inches}\"")
            else:
                profile_lines.append(f"Height: {h} cm")
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

    New user (no profile) → JS onboarding overlay appears, collects profile.
    Returning user         → chat loads directly, no onboarding.
    Dashboard profile      → render charts immediately.
    """
    await _ensure_agent()

    user = cl.user_session.get("user")
    user_id = user.identifier if user else "default_user"
    chat_profile = cl.user_session.get("chat_profile")

    if chat_profile == "Dashboard":
        await render_dashboard(user_id)
        return

    # Check if this user has a complete profile already
    profile_complete = _check_profile_complete(user_id)

    if not profile_complete:
        # New user — send a marker that JS detects to show the onboarding overlay.
        # ChatSettings NOT registered — no gear icon, no settings tab.
        await cl.Message(
            content="__ONBOARDING_NEEDED__",
        ).send()
        return

    # Returning user — profile exists, go straight to chat.
    # No settings panel registered — onboarding is the only profile setup path.


@cl.on_message
async def handle_message(message: cl.Message):
    """Runs every time the user sends a message."""
    import json as _json

    user = cl.user_session.get("user")
    user_id = user.identifier if user else "default_user"
    profile = cl.user_session.get("chat_profile")

    # ── Onboarding form submission (from JS overlay) ──────────────
    if message.content.startswith("__ONBOARDING__:"):
        try:
            payload = _json.loads(message.content[len("__ONBOARDING__:"):])
            _save_onboarding_from_overlay(payload, user_id)
            await cl.Message(
                content=(
                    "**Profile saved!** Your daily calorie target has been calculated.\n\n"
                    "Type anything to get started, or ask me a nutrition question!"
                )
            ).send()
        except Exception as e:
            logger.error(f"Onboarding parse error: {e}")
            await cl.Message(content="Something went wrong saving your profile. Please try again.").send()
        return

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


def _save_onboarding_from_overlay(payload: dict, user_id: str):
    """Parse the onboarding JSON from the JS overlay and save to store."""
    if _store is None:
        return

    units_raw = payload.get("units", "imperial")
    is_imperial = "imperial" in units_raw.lower()

    weight_val = float(payload.get("weight", 0))
    height_val = float(payload.get("height", 0))
    age_val = int(float(payload.get("age", 0)))
    sex = payload.get("sex", "male").lower()
    activity_raw = payload.get("activity", "moderate")
    tone = payload.get("tone", "balanced").lower()

    # Convert to metric for storage
    if is_imperial:
        weight_kg = round(weight_val / 2.20462, 1)
        height_cm = round(height_val * 2.54, 1)
    else:
        weight_kg = round(weight_val, 1)
        height_cm = round(height_val, 1)

    # Map activity label to key
    activity_map = {
        "sedentary": "sedentary",
        "light": "light",
        "moderate": "moderate",
        "active": "active",
        "very active": "very_active",
    }
    activity = activity_map.get(activity_raw.lower().split("(")[0].strip(), "moderate")

    # Calculate TDEE
    bmr, tdee = calculate_tdee(weight_kg, height_cm, age_val, sex, activity)

    # Store all fields
    ns = (user_id, "profile")
    _store.put(ns, "weight_kg", {"value": str(weight_kg)})
    _store.put(ns, "height_cm", {"value": str(height_cm)})
    _store.put(ns, "age", {"value": str(age_val)})
    _store.put(ns, "sex", {"value": sex})
    _store.put(ns, "activity_level", {"value": activity})
    _store.put(ns, "tdee", {"value": str(round(tdee))})
    _store.put(ns, "units", {"value": "imperial" if is_imperial else "metric"})
    _store.put(ns, "tone", {"value": tone})

    logger.info(f"Onboarding saved for {user_id}: TDEE={round(tdee)}, tone={tone}")
