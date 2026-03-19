"""Agent tools — the seven capabilities that make MacroMind useful.

Each tool is a function decorated with @tool. The agent decides WHEN to
call them based on the user's message and the tool docstrings.

The tools are created inside a factory function (create_tools) so they
can close over the retriever and store references — a Python closure.
"""

from datetime import datetime, timedelta
from langchain_core.tools import tool
from langchain_classic.retrievers import EnsembleRetriever
from langchain_tavily import TavilySearch
from langgraph.store.base import BaseStore

from macro_mate.utils import calculate_tdee


def create_tools(retriever: EnsembleRetriever, store: BaseStore) -> list:
    """Factory that builds all 7 agent tools.

    Args:
        retriever: The EnsembleRetriever from retrievers.py.
        store: The persistent store (PersistentStore or any BaseStore).

    Returns:
        A list of 7 tool functions to bind to the LLM.
    """

    # ═══════════════════════════════════════════════════════════════════
    # Tool 1 — Search the knowledge base (RAG)
    # ═══════════════════════════════════════════════════════════════════

    @tool
    def search_nutrition_knowledge(query: str) -> str:
        """Search the nutrition knowledge base for information about
        dietary guidelines, protein needs, TDEE calculations, recipes,
        and restaurant nutrition data.

        Use this tool when the user asks about:
        - Nutrition science, dietary guidelines, macronutrients
        - Recipes, ingredients, cooking instructions
        - Restaurant menu items and their nutritional content
        - Calorie and macro calculations
        """
        docs = retriever.invoke(query)
        if not docs:
            return "No relevant information found in the knowledge base."
        results = []
        for i, doc in enumerate(docs):
            source = doc.metadata.get("source_type", "unknown")
            results.append(f"[Source {i+1} ({source})]: {doc.page_content}")
        return "\n\n".join(results)

    # ═══════════════════════════════════════════════════════════════════
    # Tool 2 — Web search (Tavily)
    # ═══════════════════════════════════════════════════════════════════

    tavily = TavilySearch(max_results=3, topic="general")

    @tool
    def search_web(query: str) -> str:
        """Search the web for current nutrition, health, or food information
        not available in the knowledge base.

        Use this tool when:
        - The knowledge base doesn't have the answer
        - The user asks about current trends or recent research
        - You need up-to-date restaurant or food information
        """
        response = tavily.invoke(query)

        # TavilySearch may return a list of dicts or a dict with "results"
        if isinstance(response, list):
            results = response
        elif isinstance(response, dict):
            results = response.get("results", [])
        else:
            return "No web results found."

        if not results:
            return "No web results found."

        formatted = []
        for i, r in enumerate(results[:3]):
            if isinstance(r, dict):
                formatted.append(
                    f"[Web Source {i+1}]: {r.get('content', 'N/A')}\n"
                    f"URL: {r.get('url', 'N/A')}"
                )
            else:
                formatted.append(f"[Web Source {i+1}]: {str(r)}")
        return "\n\n".join(formatted)

    # ═══════════════════════════════════════════════════════════════════
    # Tool 3 — Log food consumption
    # ═══════════════════════════════════════════════════════════════════

    @tool
    def log_consumption(
        user_id: str,
        food_name: str,
        calories: float,
        protein_g: float,
        carbs_g: float,
        fat_g: float,
        meal_type: str = "snack",
    ) -> str:
        """Log a meal or food item the user consumed.

        Use this tool when the user tells you what they ate. Extract
        the nutritional info from the knowledge base first if needed.

        Args:
            user_id: The user's ID.
            food_name: Name of the food (e.g. "grilled chicken breast").
            calories: Total calories.
            protein_g: Grams of protein.
            carbs_g: Grams of carbohydrates.
            fat_g: Grams of fat.
            meal_type: One of "breakfast", "lunch", "dinner", "snack".
        """
        now = datetime.now()
        namespace = (user_id, "consumption")
        key = f"{meal_type}_{now.isoformat()}"

        # LOGIC: We store every field the agent passed in, PLUS:
        #   - "date": so Tool 5 can filter to today's meals only
        #   - "timestamp": for ordering meals chronologically
        #   - "text": the semantic search field — InMemoryStore uses this
        #     when you call store.search(..., query="something"). Without
        #     it, semantic search over consumption logs wouldn't work.
        store.put(namespace, key, {
            "text": f"Ate {food_name} for {meal_type}: "
                    f"{calories} cal, {protein_g}g protein, "
                    f"{carbs_g}g carbs, {fat_g}g fat",
            "food_name": food_name,
            "calories": calories,
            "protein_g": protein_g,
            "carbs_g": carbs_g,
            "fat_g": fat_g,
            "meal_type": meal_type,
            "date": now.strftime("%Y-%m-%d"),
            "timestamp": now.isoformat(),
        })

        # ── Update logging streak ──────────────────────────────────
        today_str = now.strftime("%Y-%m-%d")
        yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        streak_items = list(store.search((user_id, "streaks")))
        current_streak = streak_items[0].value if streak_items else {
            "count": 0, "last_log_date": "", "longest": 0
        }
        last_date = current_streak.get("last_log_date", "")

        if last_date == today_str:
            count = current_streak["count"]  # Already logged today
        elif last_date == yesterday_str:
            count = current_streak["count"] + 1
        else:
            count = 1

        longest = max(count, current_streak.get("longest", 0))
        store.put((user_id, "streaks"), "current", {
            "count": count, "last_log_date": today_str, "longest": longest,
        })

        streak_msg = f" | Streak: {count} day(s)" if count > 1 else ""
        return (f"Logged {food_name} ({meal_type}): {calories} cal, "
                f"{protein_g}g protein, {carbs_g}g carbs, {fat_g}g fat{streak_msg}")

    # ═══════════════════════════════════════════════════════════════════
    # Tool 4 — Manage user profile
    # ═══════════════════════════════════════════════════════════════════

    @tool
    def manage_user_profile(
        user_id: str,
        action: str = "get",
        field: str = "",
        value: str = "",
    ) -> str:
        """Get or set user biometric data and calculate TDEE.

        Use this tool to store user info like weight, height, age, sex,
        and activity level. When all fields are set, it can calculate
        TDEE using the Mifflin-St Jeor equation.

        Args:
            user_id: The user's ID.
            action: "get" to read profile, "set" to update a field,
                    "tdee" to calculate Total Daily Energy Expenditure.
            field: Which field to set (weight_kg, height_cm, age, sex,
                   activity_level, target_weight_kg, target_date, tone).
                   Ignored for "get" and "tdee". For target_weight_kg use
                   kg (convert from lbs if needed: lbs / 2.205). For
                   target_date use YYYY-MM-DD format.
            value: The value to set. Ignored for "get" and "tdee".
        """
        namespace = (user_id, "profile")

        if action == "get":
            # LOGIC: store.search(namespace) returns ALL items in that
            # namespace. Each item has .key (e.g. "weight_kg") and
            # .value (e.g. {"value": "80"}). We format them into a
            # readable string the agent can relay to the user.
            items = list(store.search(namespace))
            if not items:
                return "No profile found. Set fields with action='set'."
            lines = [f"  {item.key}: {item.value.get('value', item.value)}"
                     for item in items]
            return "User profile:\n" + "\n".join(lines)

        elif action == "set":
            # LOGIC: Each profile field is stored as its own key.
            # So setting weight creates key="weight_kg", value={"value": "80"}.
            # This means "get" can list all fields, and "tdee" can read
            # each field individually by key.
            store.put(namespace, field, {"value": value})
            return f"Set {field} to {value}."

        elif action == "tdee":
            # LOGIC: TDEE = BMR × activity_factor.
            #
            # Step 1: Collect all profile fields into one dict.
            #   The store has separate items for each field (weight_kg,
            #   height_cm, etc.), so we merge them into {"weight_kg": "80", ...}
            #
            # Step 2: Validate we have all required fields.
            #
            # Step 3: Mifflin-St Jeor equation for BMR:
            #   Male:   BMR = 10×weight + 6.25×height − 5×age + 5
            #   Female: BMR = 10×weight + 6.25×height − 5×age − 161
            #
            # Step 4: Multiply BMR by activity factor to get TDEE.

            items = list(store.search(namespace))
            profile = {item.key: item.value.get("value", "") for item in items}

            required = ["weight_kg", "height_cm", "age", "sex"]
            missing = [f for f in required if f not in profile]
            if missing:
                return (f"Cannot calculate TDEE. Missing fields: "
                        f"{', '.join(missing)}. Use action='set' to add them.")

            weight = float(profile["weight_kg"])
            height = float(profile["height_cm"])
            age = float(profile["age"])
            sex = profile["sex"].lower()
            activity = profile.get("activity_level", "moderate")

            bmr, tdee = calculate_tdee(weight, height, age, sex, activity)

            # Store the calculated TDEE so Tool 5 can reference it
            store.put(namespace, "tdee", {"value": str(round(tdee))})

            return (f"TDEE: {round(tdee)} calories/day "
                    f"(BMR: {round(bmr)}, activity: {activity})")

        return "Unknown action. Use 'get', 'set', or 'tdee'."

    # ═══════════════════════════════════════════════════════════════════
    # Tool 5 — Log exercise / calories burned
    # ═══════════════════════════════════════════════════════════════════

    @tool
    def log_exercise(
        user_id: str,
        activity_name: str,
        duration_minutes: float,
        calories_burned: float,
    ) -> str:
        """Log an exercise session the user completed.

        Use this tool when the user mentions working out, running, cycling,
        walking, gym, swimming, yoga, or any physical activity.
        Estimate calories burned if the user doesn't specify — use your
        knowledge of typical calorie burn rates for common activities.

        Args:
            user_id: The user's ID.
            activity_name: Name of the activity (e.g. "running", "cycling").
            duration_minutes: Duration in minutes.
            calories_burned: Estimated calories burned during the activity.
        """
        now = datetime.now()
        namespace = (user_id, "exercise")
        key = f"{activity_name}_{now.isoformat()}"

        store.put(namespace, key, {
            "text": f"{activity_name} for {duration_minutes} min: "
                    f"{calories_burned} cal burned",
            "activity_name": activity_name,
            "duration_min": duration_minutes,
            "calories_burned": calories_burned,
            "date": now.strftime("%Y-%m-%d"),
            "timestamp": now.isoformat(),
        })

        # Show updated remaining budget if TDEE is set
        tdee_item = store.get((user_id, "profile"), "tdee")
        budget_msg = ""
        if tdee_item:
            tdee = float(tdee_item.value.get("value", 0))
            today = now.strftime("%Y-%m-%d")
            # Sum today's food intake
            all_meals = store.search((user_id, "consumption"), query="meal", limit=100)
            today_cal = sum(
                m.value.get("calories", 0) for m in all_meals
                if m.value.get("date") == today
            )
            # Sum today's exercise burns (including this one)
            all_ex = store.search((user_id, "exercise"), query="exercise", limit=100)
            today_burned = sum(
                e.value.get("calories_burned", 0) for e in all_ex
                if e.value.get("date") == today
            )
            remaining = round(tdee + today_burned - today_cal)
            budget_msg = f" | Remaining budget: {remaining} cal"

        return (
            f"Logged {activity_name} ({duration_minutes} min, "
            f"{round(calories_burned)} cal burned){budget_msg}"
        )

    # ═══════════════════════════════════════════════════════════════════
    # Tool 6 — Daily summary
    # ═══════════════════════════════════════════════════════════════════

    @tool
    def calculate_daily_summary(user_id: str) -> str:
        """Calculate a summary of today's nutrition intake, exercise, and
        remaining calorie budget vs targets.

        Reads all meals and exercise logged today, sums up calories and
        macros, and compares against the user's TDEE. Exercise calories
        burned are added back to the daily budget.

        Args:
            user_id: The user's ID.
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # Meals
        all_meals = store.search((user_id, "consumption"), query="meal", limit=100)
        today_meals = [m for m in all_meals if m.value.get("date") == today]

        # Exercise
        all_exercises = store.search((user_id, "exercise"), query="exercise", limit=100)
        today_exercises = [e for e in all_exercises if e.value.get("date") == today]

        if not today_meals and not today_exercises:
            return f"No meals or exercise logged for today ({today})."

        # Sum macros across all of today's meals
        total_cal = sum(m.value.get("calories", 0) for m in today_meals)
        total_protein = sum(m.value.get("protein_g", 0) for m in today_meals)
        total_carbs = sum(m.value.get("carbs_g", 0) for m in today_meals)
        total_fat = sum(m.value.get("fat_g", 0) for m in today_meals)

        # Sum exercise calories burned
        total_burned = sum(e.value.get("calories_burned", 0) for e in today_exercises)
        net_cal = total_cal - total_burned

        summary = (
            f"Daily Summary for {today}:\n"
            f"  Meals logged: {len(today_meals)}\n"
            f"  Calories consumed: {round(total_cal)}\n"
            f"  Protein:  {round(total_protein)}g\n"
            f"  Carbs:    {round(total_carbs)}g\n"
            f"  Fat:      {round(total_fat)}g"
        )

        if today_exercises:
            ex_names = [e.value.get("activity_name", "exercise") for e in today_exercises]
            summary += (
                f"\n  Exercise sessions: {len(today_exercises)} ({', '.join(ex_names)})\n"
                f"  Calories burned:  {round(total_burned)}\n"
                f"  Net calories:     {round(net_cal)}"
            )

        # Compare to TDEE — remaining budget includes exercise burn-back
        tdee_item = store.get((user_id, "profile"), "tdee")
        if tdee_item:
            tdee = float(tdee_item.value.get("value", 0))
            remaining = tdee + total_burned - total_cal
            summary += (f"\n  TDEE target: {round(tdee)}\n"
                        f"  Remaining:  {round(remaining)} cal")

        # ── Append streak info ────────────────────────────────────
        streak_items = list(store.search((user_id, "streaks")))
        if streak_items:
            s = streak_items[0].value
            count = s.get("count", 0)
            longest = s.get("longest", 0)
            if count > 0:
                summary += f"\n  Streak: {count} day(s) (Best: {longest})"

        return summary

    # ═══════════════════════════════════════════════════════════════════
    # Tool 6 — Analyze progress over time
    # ═══════════════════════════════════════════════════════════════════

    @tool
    def analyze_progress(user_id: str) -> str:
        """Retrieve all stored user data (profile, meals, exercise, weight
        history) and return a structured summary for analysis.

        Use this tool when the user asks about their progress, trends,
        patterns, or wants a recap of their nutrition history.
        Examples: "analyze my progress", "how have I been doing",
        "show me my eating patterns", "recap my week".

        Args:
            user_id: The user's ID.
        """
        from collections import defaultdict, Counter
        from datetime import datetime as dt

        # ── 1. Pull the user's profile ──────────────────────────────
        profile_items = list(store.search((user_id, "profile")))
        profile = {item.key: item.value.get("value", "") for item in profile_items}

        # ── 2. Pull ALL consumption + exercise logs ─────────────────
        all_meals = list(store.search(
            (user_id, "consumption"), query="meal food", limit=500
        ))
        all_exercises = list(store.search(
            (user_id, "exercise"), query="exercise activity", limit=500
        ))

        if not all_meals and not profile:
            return "No data found. Log some meals and set up your profile first."

        # ── 3. Build the profile section ────────────────────────────
        sections = []
        if profile:
            profile_lines = [f"  {k}: {v}" for k, v in profile.items()]
            sections.append("PROFILE:\n" + "\n".join(profile_lines))

        # ── 4. Group meals by date ──────────────────────────────────
        # Group exercises by date
        exercise_by_date = defaultdict(list)
        for e in all_exercises:
            d = e.value.get("date", "unknown")
            exercise_by_date[d].append(e.value)

        if all_meals:
            days = defaultdict(list)
            for m in all_meals:
                date = m.value.get("date", "unknown")
                days[date].append(m.value)

            sections.append(f"MEAL LOG ({len(all_meals)} meals across {len(days)} days):")

            for date in sorted(days.keys()):
                meals = days[date]
                day_cal = sum(m.get("calories", 0) for m in meals)
                day_pro = sum(m.get("protein_g", 0) for m in meals)
                day_carb = sum(m.get("carbs_g", 0) for m in meals)
                day_fat = sum(m.get("fat_g", 0) for m in meals)

                # Exercise for this date
                day_exercises = exercise_by_date.get(date, [])
                day_burned = sum(e.get("calories_burned", 0) for e in day_exercises)
                day_net = day_cal - day_burned

                ex_str = ""
                if day_exercises:
                    ex_names = [e.get("activity_name", "exercise") for e in day_exercises]
                    ex_str = (f"\n    Exercise: {', '.join(ex_names)} "
                              f"({round(day_burned)} cal burned)\n"
                              f"    Net calories: {round(day_net)}")

                sections.append(
                    f"\n  {date} ({len(meals)} meals):\n"
                    f"    Consumed: {round(day_cal)} cal, {round(day_pro)}g protein, "
                    f"{round(day_carb)}g carbs, {round(day_fat)}g fat{ex_str}"
                )
                for m in meals:
                    sections.append(
                        f"    - {m.get('food_name', 'unknown')} ({m.get('meal_type', '')}): "
                        f"{m.get('calories', 0)} cal"
                    )

            # ── 5. Compute overall averages ─────────────────────────
            total_days = len(days)
            total_cal = sum(m.value.get("calories", 0) for m in all_meals)
            total_pro = sum(m.value.get("protein_g", 0) for m in all_meals)
            total_burned = sum(e.value.get("calories_burned", 0) for e in all_exercises)

            avg_cal = round(total_cal / total_days)
            avg_burned = round(total_burned / total_days) if total_days else 0
            avg_net = round((total_cal - total_burned) / total_days) if total_days else 0

            avg_section = (
                f"\nAVERAGES ({total_days} days):\n"
                f"  Avg calories consumed/day: {avg_cal}\n"
                f"  Avg protein/day:  {round(total_pro / total_days)}g"
            )
            if total_burned > 0:
                avg_section += (
                    f"\n  Avg exercise burned/day:  {avg_burned}\n"
                    f"  Avg net calories/day:     {avg_net}"
                )
            sections.append(avg_section)

            # Compare to TDEE — use NET calories
            if "tdee" in profile:
                tdee = float(profile["tdee"])
                diff = avg_net - tdee
                direction = "over" if diff > 0 else "under"
                sections.append(
                    f"  TDEE target: {round(tdee)} cal/day\n"
                    f"  Avg daily net difference: {round(abs(diff))} cal {direction} target"
                )

            # ── 6. Weekday vs. weekend comparison (net calories) ──
            weekday_nets = []
            weekend_nets = []
            for date_str, meals_list in days.items():
                try:
                    day_of_week = dt.strptime(date_str, "%Y-%m-%d").weekday()
                except ValueError:
                    continue
                day_total = sum(m.get("calories", 0) for m in meals_list)
                day_burn = sum(e.get("calories_burned", 0) for e in exercise_by_date.get(date_str, []))
                day_net = day_total - day_burn
                if day_of_week < 5:
                    weekday_nets.append(day_net)
                else:
                    weekend_nets.append(day_net)

            if weekday_nets and weekend_nets:
                avg_weekday = round(sum(weekday_nets) / len(weekday_nets))
                avg_weekend = round(sum(weekend_nets) / len(weekend_nets))
                sections.append(
                    f"\nWEEKDAY vs WEEKEND (net calories):\n"
                    f"  Avg weekday net: {avg_weekday}\n"
                    f"  Avg weekend net: {avg_weekend}\n"
                    f"  Difference: {abs(avg_weekday - avg_weekend)} cal "
                    f"({'higher on weekends' if avg_weekend > avg_weekday else 'higher on weekdays'})"
                )

            # ── 7. Most logged foods (top 5 by frequency) ────────
            food_counts = Counter()
            for m in all_meals:
                name = m.value.get("food_name", "")
                if name:
                    food_counts[name.lower()] += 1
            if food_counts:
                top_foods = food_counts.most_common(5)
                lines = [f"    {i+1}. {name} ({count}x)" for i, (name, count) in enumerate(top_foods)]
                sections.append(f"\nMOST LOGGED FOODS:\n" + "\n".join(lines))

            # ── 8. Meal type gaps ─────────────────────────────────
            meal_type_by_day = defaultdict(set)
            for m in all_meals:
                date = m.value.get("date", "")
                mt = m.value.get("meal_type", "")
                if date and mt:
                    meal_type_by_day[date].add(mt)

            if meal_type_by_day:
                total_tracked_days = len(meal_type_by_day)
                type_day_counts = defaultdict(int)
                for day_types in meal_type_by_day.values():
                    for t in day_types:
                        type_day_counts[t] += 1

                gap_lines = []
                for mt in ["breakfast", "lunch", "dinner"]:
                    count = type_day_counts.get(mt, 0)
                    if count < total_tracked_days:
                        gap_lines.append(
                            f"    {mt.capitalize()}: logged {count} of {total_tracked_days} days"
                        )
                if gap_lines:
                    sections.append(f"\nMEAL GAPS (skipped meals):\n" + "\n".join(gap_lines))

            # ── 9. Macro consistency (protein) ────────────────────
            daily_proteins = []
            for date_str, meals_list in days.items():
                day_pro = sum(m.get("protein_g", 0) for m in meals_list)
                daily_proteins.append(day_pro)

            if len(daily_proteins) > 2:
                avg_pro = sum(daily_proteins) / len(daily_proteins)
                variance = sum((p - avg_pro) ** 2 for p in daily_proteins) / len(daily_proteins)
                std_dev = variance ** 0.5
                consistency = "consistent" if std_dev < 20 else "inconsistent" if std_dev > 40 else "somewhat variable"
                sections.append(
                    f"\nPROTEIN CONSISTENCY:\n"
                    f"  Avg daily protein: {round(avg_pro)}g\n"
                    f"  Variation: {consistency} (std dev: {round(std_dev)}g)"
                )

        # ── 10. Exercise summary ──────────────────────────────────
        if all_exercises:
            ex_counter = Counter()
            total_ex_cal = 0
            total_ex_min = 0
            for e in all_exercises:
                ex_counter[e.value.get("activity_name", "exercise")] += 1
                total_ex_cal += e.value.get("calories_burned", 0)
                total_ex_min += e.value.get("duration_min", 0)
            ex_lines = [f"    {name}: {count}x" for name, count in ex_counter.most_common()]
            sections.append(
                f"\nEXERCISE SUMMARY ({len(all_exercises)} sessions):\n"
                f"  Total calories burned: {round(total_ex_cal)}\n"
                f"  Total duration: {round(total_ex_min)} min\n"
                + "\n".join(ex_lines)
            )

        return "\n".join(sections)

    # ═══════════════════════════════════════════════════════════════════
    # Tool 7 — USDA FoodData Central lookup
    # ═══════════════════════════════════════════════════════════════════

    @tool
    def search_usda_foods(query: str) -> str:
        """Search the USDA FoodData Central database for detailed,
        verified nutrition information about any food item.

        Use this tool when:
        - The user asks for exact macros of a specific food (not a restaurant item)
        - You need precise, USDA-verified nutrition data
        - The knowledge base doesn't have detailed macros for a food

        Do NOT use for restaurant menu items (use search_nutrition_knowledge
        or search_web for those).

        Args:
            query: Name of the food to search for (e.g. "chicken breast",
                   "banana", "brown rice").
        """
        import requests
        from macro_mate.config import USDA_API_KEY

        if not USDA_API_KEY:
            return "USDA API key not configured. Set USDA_API_KEY in .env."

        url = "https://api.nal.usda.gov/fdc/v1/foods/search"
        params = {
            "api_key": USDA_API_KEY,
            "query": query,
            "pageSize": 3,
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            return f"Error querying USDA API: {e}"

        foods = data.get("foods", [])
        if not foods:
            return f"No results found for '{query}' in USDA FoodData Central."

        results = []
        for i, food in enumerate(foods[:3]):
            name = food.get("description", "Unknown")
            nutrients = {}
            for nutrient in food.get("foodNutrients", []):
                n_name = nutrient.get("nutrientName", "")
                n_value = nutrient.get("value", 0)
                n_unit = nutrient.get("unitName", "")
                if "Energy" in n_name and n_unit == "KCAL":
                    nutrients["calories"] = f"{n_value} kcal"
                elif "Protein" in n_name:
                    nutrients["protein"] = f"{n_value}g"
                elif "Carbohydrate" in n_name:
                    nutrients["carbs"] = f"{n_value}g"
                elif n_name == "Total lipid (fat)":
                    nutrients["fat"] = f"{n_value}g"
                elif "Fiber" in n_name:
                    nutrients["fiber"] = f"{n_value}g"
                elif "Sugars, total" in n_name:
                    nutrients["sugar"] = f"{n_value}g"
                elif "Sodium" in n_name:
                    nutrients["sodium"] = f"{n_value}mg"

            serving = food.get("servingSize", "")
            serving_unit = food.get("servingSizeUnit", "")
            serving_str = f" (per {serving}{serving_unit})" if serving else " (per 100g)"

            nutrient_lines = [f"    {k}: {v}" for k, v in nutrients.items()]
            results.append(
                f"[USDA Result {i+1}]: {name}{serving_str}\n"
                + "\n".join(nutrient_lines)
            )

        return "\n\n".join(results)

    # ─── Return all 7 tools ──────────────────────────────────────────

    return [
        search_nutrition_knowledge,
        search_web,
        log_consumption,
        manage_user_profile,
        log_exercise,
        calculate_daily_summary,
        analyze_progress,
        search_usda_foods,
    ]
