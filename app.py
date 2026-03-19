"""Chainlit entry point — boots the app and handles user messages.

Run with:  chainlit run app.py

Three flows:
  - Onboarding: new users set up their profile (weight, height, age, sex, activity)
  - Chat: conversational agent with 7 nutrition tools
  - Dashboard: visual charts of calories, macros, and progress
"""

import os
import logging
import asyncio
from datetime import datetime, timedelta

import chainlit as cl
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
        cl.ChatProfile(
            name="Insights",
            markdown_description="AI-powered analysis of your nutrition patterns and progress",
            icon="https://cdn-icons-png.flaticon.com/512/2103/2103633.png",
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
    required = {"units", "weight_kg", "height_cm", "age", "sex", "activity_level"}
    return all(profile.get(f, "").strip() for f in required)


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

    # Today's exercise
    all_exercises = list(_store.search((user_id, "exercise"), query="exercise activity", limit=500))
    today_exercises = [e for e in all_exercises if e.value.get("date") == today]
    total_burned = sum(e.value.get("calories_burned", 0) for e in today_exercises)

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

    # 1. Calorie gauge (accounts for exercise: budget = tdee + burned)
    if tdee > 0:
        effective_budget = tdee + total_burned
        remaining = max(0, effective_budget - total_cal)
        pct = min(100, round((total_cal / effective_budget) * 100))
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

    # 3. Weekly calorie trend (if multi-day data exists) — shows consumed + burned
    from collections import defaultdict
    days_consumed = defaultdict(float)
    days_burned = defaultdict(float)
    for m in all_meals:
        d = m.value.get("date", "")
        if d:
            days_consumed[d] += m.value.get("calories", 0)
    for e in all_exercises:
        d = e.value.get("date", "")
        if d:
            days_burned[d] += e.value.get("calories_burned", 0)

    all_dates = set(days_consumed.keys()) | set(days_burned.keys())
    if len(all_dates) > 1:
        sorted_dates = sorted(all_dates)[-7:]
        consumed_vals = [round(days_consumed.get(d, 0)) for d in sorted_dates]
        burned_vals = [round(days_burned.get(d, 0)) for d in sorted_dates]
        net_vals = [c - b for c, b in zip(consumed_vals, burned_vals)]

        trend_fig = go.Figure()
        trend_fig.add_trace(go.Bar(
            x=sorted_dates, y=consumed_vals, name="Consumed",
            marker_color=_SKY,
            marker_line_width=0,
        ))
        if any(b > 0 for b in burned_vals):
            trend_fig.add_trace(go.Bar(
                x=sorted_dates, y=[-b for b in burned_vals], name="Burned",
                marker_color=_CORAL,
                marker_line_width=0,
            ))
        if tdee > 0:
            # If user has a weight loss target, show Target Intake line instead of TDEE
            tw_kg = profile.get("target_weight_kg", "")
            td_str = profile.get("target_date", "")
            if tw_kg and td_str and tw_kg.strip() and td_str.strip():
                try:
                    w_kg = float(profile.get("weight_kg", 0))
                    t_kg = float(tw_kg)
                    goal_date = datetime.strptime(td_str, "%Y-%m-%d")
                    days_left = max(1, (goal_date - datetime.now()).days)
                    total_deficit = (w_kg - t_kg) * 7700  # ~7700 cal per kg
                    daily_deficit = min(total_deficit / days_left, 1000)  # cap at 1000 cal/day
                    target_intake = round(tdee - daily_deficit)
                    ref_label = f"Target: {target_intake}"
                except (ValueError, TypeError):
                    target_intake = tdee
                    ref_label = f"TDEE: {round(tdee)}"
            else:
                target_intake = tdee
                ref_label = f"TDEE: {round(tdee)}"
            trend_fig.add_hline(
                y=target_intake, line_dash="dot", line_color=_CORAL, line_width=2,
                annotation_text=ref_label,
                annotation_font=dict(color=_CORAL, size=12, family=_FONT),
            )
        trend_fig.update_layout(
            title_text="Daily Calories (Last 7 Days)",
            title_x=0.5,
            title_font=dict(color="white", size=16, family=_FONT),
            yaxis_title="Calories",
            yaxis=dict(
                title_font=dict(color=_GRAY, size=12),
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
                title_font=dict(color=_GRAY, size=12),
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
        # Show target weight if set
        if "target_weight_kg" in profile:
            tw = float(profile["target_weight_kg"])
            tw_str = f"{round(tw * 2.20462)} lbs" if units == "imperial" else f"{tw} kg"
            td = profile.get("target_date", "")
            goal_str = f"Goal: {tw_str}"
            if td:
                goal_str += f" by {td}"
            profile_lines.append(goal_str)
        profile_text = " | ".join(profile_lines) if profile_lines else "*Profile incomplete*"

    today_text = f"**Today:** {round(total_cal)} cal consumed"
    if total_burned > 0:
        today_text += f" | {round(total_burned)} cal burned | {round(total_cal - total_burned)} net"
    today_text += f" | {round(total_protein)}g protein | {round(total_carbs)}g carbs | {round(total_fat)}g fat"
    if tdee > 0:
        remaining = round(tdee + total_burned - total_cal)
        today_text += f" | **{remaining} cal remaining**"

    meals_text = f"**Meals logged today:** {len(today_meals)}"
    if today_exercises:
        meals_text += f" | **Exercise:** {len(today_exercises)} session(s), {round(total_burned)} cal burned"

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

    # Dashboard profile — render charts immediately.
    if chat_profile == "Dashboard":
        await render_dashboard(user_id)
        return

    # Insights profile — AI-generated nutrition analysis.
    if chat_profile == "Insights":
        await render_insights(user_id)
        return

    # Check if this user has a complete profile already
    profile_complete = _check_profile_complete(user_id)

    if not profile_complete:
        # New user — send a marker that JS detects to show the onboarding overlay.
        await cl.Message(
            content="MACROMIND_ONBOARDING_START",
        ).send()
        return

    # Returning user — profile exists, go straight to chat.


@cl.on_message
async def handle_message(message: cl.Message):
    """Runs every time the user sends a message."""
    import json as _json

    user = cl.user_session.get("user")
    user_id = user.identifier if user else "default_user"
    profile = cl.user_session.get("chat_profile")

    # ── Dashboard mode: refresh charts or prompt to switch to Chat ──
    if profile == "Dashboard":
        lower = message.content.lower()
        if any(kw in lower for kw in ["chat", "talk", "macromind"]):
            await cl.Message(
                content="To talk to MacroMind, switch to the **Chat** profile using the dropdown at the top."
            ).send()
        else:
            await render_dashboard(user_id)
        return

    # ── Insights mode: regenerate analysis ──
    if profile == "Insights":
        await render_insights(user_id)
        return

    # ── Seed demo data command ────────────────────────────────────
    if message.content.strip().lower() == "/seed":
        _seed_demo_data(user_id)
        await cl.Message(content="Demo data seeded! Switch to **Dashboard** or **Insights** to see it.").send()
        return

    # ── Profile view/update command ─────────────────────────────
    if message.content.strip().lower() == "/profile":
        if _store is None:
            await cl.Message(content="Store not ready yet.").send()
            return
        items = list(_store.search((user_id, "profile")))
        prof = {item.key: item.value.get("value", "") for item in items}
        if not prof:
            await cl.Message(content="No profile found. Complete onboarding first.").send()
            return
        units = prof.get("units", "metric")
        is_imp = units == "imperial"
        lines = []
        if "weight_kg" in prof:
            w = float(prof["weight_kg"])
            lines.append(f"**Weight:** {round(w * 2.20462)} lbs" if is_imp else f"**Weight:** {w} kg")
        if "height_cm" in prof:
            h = float(prof["height_cm"])
            if is_imp:
                ti = round(h / 2.54)
                ft, inch = divmod(ti, 12)
                lines.append(f"**Height:** {ft}'{inch}\"")
            else:
                lines.append(f"**Height:** {h} cm")
        lines.append(f"**Age:** {prof.get('age', '?')}")
        lines.append(f"**Sex:** {prof.get('sex', '?').capitalize()}")
        lines.append(f"**Activity:** {prof.get('activity_level', '?')}")
        lines.append(f"**TDEE:** {prof.get('tdee', '?')} cal/day")
        lines.append(f"**Tone:** {prof.get('tone', 'balanced')}")
        tw = prof.get("target_weight_kg", "")
        td = prof.get("target_date", "")
        if tw and tw.strip():
            tw_str = f"{round(float(tw) * 2.20462)} lbs" if is_imp else f"{tw} kg"
            lines.append(f"**Target Weight:** {tw_str}")
        if td and td.strip():
            lines.append(f"**Target Date:** {td}")
        profile_md = "## Your Profile\n\n" + "\n".join(lines)
        profile_md += "\n\n---\n*To update, just tell me — e.g. \"change my target weight to 155 lbs\" or \"set my target date to July 1\"*"
        await cl.Message(content=profile_md).send()
        return

    # ── Onboarding form submission (from JS overlay) ──────────────
    if message.content.startswith("__ONBOARDING__:"):
        try:
            payload = _json.loads(message.content[len("__ONBOARDING__:"):])
            error = _save_onboarding_from_overlay(payload, user_id)
            if error:
                await cl.Message(content=error).send()
                await cl.Message(content="MACROMIND_ONBOARDING_START").send()
                return

            # Send immediate feedback so users never see a blank/stuck screen.
            await cl.Message(
                content="Profile saved. Building your personalized welcome..."
            ).send()

            # Build a profile summary for the agent to use as a welcome
            profile_items = list(_store.search((user_id, "profile")))
            profile = {item.key: item.value.get("value", "") for item in profile_items}

            units = profile.get("units", "imperial")
            is_imp = units == "imperial"
            w_kg = float(profile.get("weight_kg", 0))
            h_cm = float(profile.get("height_cm", 0))
            weight_str = f"{round(w_kg * 2.20462)} lbs" if is_imp else f"{w_kg} kg"
            if is_imp:
                total_in = round(h_cm / 2.54)
                ft, inch = divmod(total_in, 12)
                height_str = f"{ft}'{inch}\""
            else:
                height_str = f"{h_cm} cm"

            summary_lines = [
                f"Current weight: {weight_str}",
                f"Height: {height_str}",
                f"Age: {profile.get('age', '?')}",
                f"Sex: {profile.get('sex', '?').capitalize()}",
                f"Activity: {profile.get('activity_level', '?')}",
                f"TDEE: {profile.get('tdee', '?')} cal/day",
            ]
            tw_kg = profile.get("target_weight_kg", "")
            td = profile.get("target_date", "")
            if tw_kg:
                tw_str = f"{round(float(tw_kg) * 2.20462)} lbs" if is_imp else f"{tw_kg} kg"
                summary_lines.append(f"Target weight: {tw_str}")
            if td:
                summary_lines.append(f"Target date: {td}")

            profile_summary = " | ".join(summary_lines)

            # Craft the welcome prompt for the agent
            if tw_kg and td:
                welcome_prompt = (
                    f"Here is my profile: {profile_summary}. "
                    f"Welcome me to MacroMind! Give me a brief personalized summary "
                    f"of my profile and a high-level plan to reach my target weight "
                    f"by my target date. Include the daily calorie deficit needed and "
                    f"expected weekly weight loss rate. Keep it concise and motivating."
                )
            elif tw_kg:
                welcome_prompt = (
                    f"Here is my profile: {profile_summary}. "
                    f"Welcome me to MacroMind! Summarize my profile and give me a "
                    f"brief plan to reach my target weight. Keep it concise."
                )
            else:
                welcome_prompt = (
                    f"Here is my profile: {profile_summary}. "
                    f"Welcome me to MacroMind! Give me a brief personalized summary "
                    f"of my profile and TDEE. Ask about my goals so you can help me "
                    f"create a plan. Keep it concise and friendly."
                )

            # Invoke the agent for a personalized welcome.
            # Run in a worker thread + timeout to avoid a blank UI if model call is slow.
            try:
                config = {"configurable": {"thread_id": cl.context.session.id}}
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        agent.invoke,
                        {"messages": [HumanMessage(content=welcome_prompt)], "user_id": user_id},
                        config,
                    ),
                    timeout=60,
                )
                ai_msg = response["messages"][-1]
                await cl.Message(content=ai_msg.content).send()
            except Exception as invoke_err:
                logger.error(f"Onboarding welcome generation failed: {invoke_err}")
                fallback = (
                    "You are all set. Your profile is saved and your nutrition targets "
                    "are active. Ask me to create your first weekly plan, meal ideas, "
                    "or a daily calorie/macro breakdown."
                )
                await cl.Message(content=fallback).send()

        except Exception as e:
            logger.error(f"Onboarding parse error: {e}")
            await cl.Message(content="Something went wrong saving your profile. Please try again.").send()
        return

    # ── Chat mode ─────────────────────────────────────────────────
    config = {"configurable": {"thread_id": cl.context.session.id}}

    response = agent.invoke(
        {
            "messages": [HumanMessage(content=message.content)],
            "user_id": user_id,
        },
        config=config,
    )

    ai_message = response["messages"][-1]
    await cl.Message(content=ai_message.content).send()


async def render_insights(user_id: str):
    """Generate an AI-powered nutrition insights report from all user data."""
    if _store is None:
        await cl.Message(content="Insights are loading... please wait a moment and try again.").send()
        return

    from collections import defaultdict

    # Pull all data
    profile_items = list(_store.search((user_id, "profile")))
    profile = {item.key: item.value.get("value", "") for item in profile_items}

    all_meals = list(_store.search((user_id, "consumption"), query="meal food", limit=500))
    all_exercises = list(_store.search((user_id, "exercise"), query="exercise activity", limit=500))

    if not all_meals:
        await cl.Message(
            content="## MacroMind Insights\n\n"
                    "*No meal data yet!* Switch to **Chat** to start logging meals, "
                    "then come back here for a personalized analysis of your nutrition patterns."
        ).send()
        return

    # Build a structured data summary for the agent
    days = defaultdict(list)
    for m in all_meals:
        d = m.value.get("date", "unknown")
        days[d].append(m.value)

    exercise_by_date = defaultdict(list)
    for e in all_exercises:
        d = e.value.get("date", "unknown")
        exercise_by_date[d].append(e.value)

    data_lines = []
    data_lines.append(f"Total: {len(all_meals)} meals across {len(days)} days")
    if profile.get("tdee"):
        data_lines.append(f"TDEE target: {profile['tdee']} cal/day")
    if profile.get("weight_kg"):
        data_lines.append(f"Weight: {profile['weight_kg']} kg")
    if profile.get("target_weight_kg") and profile["target_weight_kg"]:
        data_lines.append(f"Target weight: {profile['target_weight_kg']} kg by {profile.get('target_date', '?')}")

    for date in sorted(days.keys()):
        meals = days[date]
        day_cal = sum(m.get("calories", 0) for m in meals)
        day_pro = sum(m.get("protein_g", 0) for m in meals)
        day_carb = sum(m.get("carbs_g", 0) for m in meals)
        day_fat = sum(m.get("fat_g", 0) for m in meals)
        meal_types = [m.get("meal_type", "?") for m in meals]
        food_names = [m.get("food_name", "?") for m in meals]

        day_ex = exercise_by_date.get(date, [])
        day_burned = sum(e.get("calories_burned", 0) for e in day_ex)

        line = (f"  {date}: {round(day_cal)} cal, {round(day_pro)}g pro, "
                f"{round(day_carb)}g carb, {round(day_fat)}g fat | "
                f"meals: {', '.join(meal_types)} | foods: {', '.join(food_names)}")
        if day_burned > 0:
            line += f" | exercise: {round(day_burned)} cal burned"
        data_lines.append(line)

    data_summary = "\n".join(data_lines)

    insights_prompt = (
        f"Here is my complete nutrition data:\n{data_summary}\n\n"
        f"Generate a personalized nutrition insights report with these sections:\n"
        f"1. **Eating Patterns** — timing, consistency, weekend vs weekday trends, skipped meals\n"
        f"2. **Macro Balance** — protein/carbs/fat distribution, daily protein consistency\n"
        f"3. **What's Working** — positive trends, good habits, strengths\n"
        f"4. **Areas to Improve** — specific, actionable suggestions with numbers\n"
        f"5. **This Week's Focus** — 2-3 concrete goals for the coming week\n\n"
        f"Keep it engaging, concise, and use bullet points. Reference specific days and foods from the data."
    )

    await cl.Message(content="## MacroMind Insights\n\n*Analyzing your nutrition data...*").send()

    try:
        config = {"configurable": {"thread_id": f"insights_{user_id}"}}
        response = await asyncio.wait_for(
            asyncio.to_thread(
                agent.invoke,
                {"messages": [HumanMessage(content=insights_prompt)], "user_id": user_id},
                config,
            ),
            timeout=90,
        )
        ai_msg = response["messages"][-1]
        await cl.Message(content=ai_msg.content).send()
    except Exception as e:
        logger.error(f"Insights generation failed: {e}")
        await cl.Message(
            content="Could not generate insights right now. Try again in a moment."
        ).send()


def _seed_demo_data(user_id: str):
    """Pre-populate 14 days of realistic meal + exercise data for demo purposes.

    Only runs if the user has zero consumption data. Safe to call multiple times.
    """
    if _store is None:
        return

    # Check if user already has data
    existing = list(_store.search((user_id, "consumption"), query="meal", limit=1))
    if existing:
        return  # Don't overwrite real data

    import random
    random.seed(42)  # Reproducible demo data

    today = datetime.now()
    ns_meals = (user_id, "consumption")
    ns_exercise = (user_id, "exercise")

    # Seed profile if user doesn't have one (demo build: 170 lbs, 5'10", 28M moderate)
    ns_profile = (user_id, "profile")
    profile_items = list(_store.search(ns_profile))
    if not profile_items:
        _store.put(ns_profile, "weight_kg", {"value": "77.1"})
        _store.put(ns_profile, "height_cm", {"value": "177.8"})
        _store.put(ns_profile, "age", {"value": "28"})
        _store.put(ns_profile, "sex", {"value": "male"})
        _store.put(ns_profile, "activity_level", {"value": "moderate"})
        _store.put(ns_profile, "tdee", {"value": "2739"})
        _store.put(ns_profile, "units", {"value": "imperial"})
        _store.put(ns_profile, "tone", {"value": "balanced"})
        _store.put(ns_profile, "target_weight_kg", {"value": "72.6"})
        _store.put(ns_profile, "target_date", {"value": "2026-06-01"})

    # Realistic meal templates for a 170 lb male targeting ~2200-2500 cal/day, ~130-150g protein
    # (food_name, calories, protein, carbs, fat, meal_type)
    breakfasts = [
        ("4-egg omelet with cheese and veggies", 520, 38, 8, 36, "breakfast"),
        ("Greek yogurt parfait with granola and berries", 450, 30, 52, 14, "breakfast"),
        ("oatmeal with protein powder and banana", 480, 32, 62, 12, "breakfast"),
        ("avocado toast with 2 eggs and turkey bacon", 540, 34, 36, 28, "breakfast"),
        ("protein smoothie with banana and peanut butter", 460, 36, 42, 16, "breakfast"),
        ("breakfast burrito with eggs and sausage", 580, 32, 44, 28, "breakfast"),
    ]
    lunches = [
        ("grilled chicken Caesar salad with croutons", 620, 48, 24, 32, "lunch"),
        ("turkey and avocado wrap with side salad", 640, 42, 48, 26, "lunch"),
        ("chicken burrito bowl with rice and beans", 720, 44, 72, 22, "lunch"),
        ("tuna melt sandwich with soup", 580, 40, 42, 24, "lunch"),
        ("poke bowl with brown rice and edamame", 650, 38, 62, 22, "lunch"),
        ("grilled chicken sandwich with sweet potato fries", 680, 42, 58, 26, "lunch"),
    ]
    dinners = [
        ("8oz salmon with brown rice and broccoli", 680, 48, 52, 22, "dinner"),
        ("8oz grilled steak with sweet potato and asparagus", 720, 52, 44, 30, "dinner"),
        ("chicken stir-fry with vegetables and rice", 640, 44, 56, 20, "dinner"),
        ("pasta with marinara and ground turkey", 700, 40, 74, 22, "dinner"),
        ("shrimp tacos with slaw and guacamole", 620, 36, 48, 26, "dinner"),
        ("baked chicken thighs with roasted vegetables", 660, 50, 34, 28, "dinner"),
        ("burger and fries (dining out)", 980, 42, 78, 52, "dinner"),
        ("pizza night (3 slices)", 840, 32, 84, 36, "dinner"),
    ]
    snacks = [
        ("protein bar", 240, 22, 26, 8, "snack"),
        ("apple with almond butter", 280, 8, 30, 16, "snack"),
        ("trail mix and jerky", 320, 18, 22, 18, "snack"),
        ("cottage cheese with fruit", 220, 24, 18, 5, "snack"),
        ("protein shake", 200, 30, 10, 4, "snack"),
    ]
    exercises = [
        ("running", 30, 300),
        ("cycling", 45, 350),
        ("walking", 40, 180),
        ("weight training", 50, 280),
        ("yoga", 30, 120),
    ]

    for day_offset in range(14, -1, -1):  # includes today (day_offset=0)
        day = today - timedelta(days=day_offset)
        date_str = day.strftime("%Y-%m-%d")
        day_of_week = day.weekday()
        is_weekend = day_of_week >= 5

        # Skip breakfast sometimes (pattern for agent to detect — ~25% skip rate)
        if random.random() > 0.25:
            b = random.choice(breakfasts)
            _store.put(ns_meals, f"breakfast_{date_str}", {
                "text": f"Ate {b[0]} for breakfast: {b[1]} cal, {b[2]}g protein, {b[3]}g carbs, {b[4]}g fat",
                "food_name": b[0], "calories": b[1], "protein_g": b[2],
                "carbs_g": b[3], "fat_g": b[4], "meal_type": b[5],
                "date": date_str, "timestamp": f"{date_str}T08:30:00",
            })

        # Lunch (almost always)
        l = random.choice(lunches)
        _store.put(ns_meals, f"lunch_{date_str}", {
            "text": f"Ate {l[0]} for lunch: {l[1]} cal, {l[2]}g protein, {l[3]}g carbs, {l[4]}g fat",
            "food_name": l[0], "calories": l[1], "protein_g": l[2],
            "carbs_g": l[3], "fat_g": l[4], "meal_type": l[5],
            "date": date_str, "timestamp": f"{date_str}T12:30:00",
        })

        # Dinner (always, but weekends tend to be higher calorie)
        if is_weekend and random.random() > 0.4:
            d = random.choice(dinners[-2:])  # burger/pizza on weekends
        else:
            d = random.choice(dinners[:-2])  # healthier on weekdays
        _store.put(ns_meals, f"dinner_{date_str}", {
            "text": f"Ate {d[0]} for dinner: {d[1]} cal, {d[2]}g protein, {d[3]}g carbs, {d[4]}g fat",
            "food_name": d[0], "calories": d[1], "protein_g": d[2],
            "carbs_g": d[3], "fat_g": d[4], "meal_type": d[5],
            "date": date_str, "timestamp": f"{date_str}T19:00:00",
        })

        # Snack (most days — protein targets need it)
        if random.random() > 0.2:
            s = random.choice(snacks)
            _store.put(ns_meals, f"snack_{date_str}", {
                "text": f"Ate {s[0]} for snack: {s[1]} cal, {s[2]}g protein, {s[3]}g carbs, {s[4]}g fat",
                "food_name": s[0], "calories": s[1], "protein_g": s[2],
                "carbs_g": s[3], "fat_g": s[4], "meal_type": s[5],
                "date": date_str, "timestamp": f"{date_str}T15:30:00",
            })

        # Exercise (3-4 times per week, mostly weekdays)
        if not is_weekend and random.random() > 0.5:
            ex = random.choice(exercises)
            _store.put(ns_exercise, f"{ex[0]}_{date_str}", {
                "text": f"{ex[0]} for {ex[1]} min: {ex[2]} cal burned",
                "activity_name": ex[0], "duration_min": ex[1],
                "calories_burned": ex[2],
                "date": date_str, "timestamp": f"{date_str}T07:00:00",
            })

    logger.info(f"Seeded 14 days of demo data for user {user_id}")


def _save_onboarding_from_overlay(payload: dict, user_id: str) -> str | None:
    """Parse onboarding JSON, validate it, and save profile fields."""
    if _store is None:
        return "Storage is not available yet. Please try again in a few seconds."

    required_fields = ("units", "weight", "height", "age", "sex", "activity")
    missing = [field for field in required_fields if str(payload.get(field, "")).strip() == ""]
    if missing:
        return "Please fill in all required onboarding fields before continuing."

    units_raw = str(payload.get("units", "imperial")).strip().lower()
    is_imperial = "imperial" in units_raw

    try:
        weight_val = float(payload.get("weight", 0))
        height_val = float(payload.get("height", 0))
        age_val = int(float(payload.get("age", 0)))
    except (TypeError, ValueError):
        return "Weight, height, and age must be valid numbers."

    if weight_val <= 0 or height_val <= 0 or age_val <= 0:
        return "Weight, height, and age must all be positive values."

    sex = str(payload.get("sex", "male")).strip().lower()
    if sex not in {"male", "female"}:
        return "Biological sex must be either Male or Female."

    activity_raw = str(payload.get("activity", "moderate")).strip().lower()
    tone_raw = str(payload.get("tone", "balanced")).strip().lower()
    tone_map = {"supportive": "supportive", "balanced": "balanced", "tough love": "tough love"}
    tone = tone_map.get(tone_raw, "balanced")

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
    activity = activity_map.get(activity_raw.split("(")[0].strip(), "moderate")

    # Calculate TDEE
    bmr, tdee = calculate_tdee(weight_kg, height_cm, age_val, sex, activity)

    # Target weight (optional)
    target_weight_raw = str(payload.get("target_weight", "")).strip()
    target_date = str(payload.get("target_date", "")).strip()
    if bool(target_weight_raw) != bool(target_date):
        return "Please provide both target weight and target date, or leave both blank."

    target_weight_kg = None
    if target_weight_raw:
        try:
            tw = float(target_weight_raw)
        except ValueError:
            return "Target weight must be a valid number."
        if tw <= 0:
            return "Target weight must be a positive number."
        target_weight_kg = round(tw / 2.20462, 1) if is_imperial else round(tw, 1)
        try:
            goal_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            return "Target date must use a valid YYYY-MM-DD date."
        if goal_date <= datetime.now().date():
            return "Target date must be in the future."

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
    if target_weight_kg is not None:
        _store.put(ns, "target_weight_kg", {"value": str(target_weight_kg)})
        _store.put(ns, "target_date", {"value": target_date})
    else:
        # Clear stale target values when user does not set goals.
        _store.put(ns, "target_weight_kg", {"value": ""})
        _store.put(ns, "target_date", {"value": ""})

    logger.info(f"Onboarding saved for {user_id}: TDEE={round(tdee)}, tone={tone}")
    return None
