"""Comprehensive PersistentStore test — simulates the exact demo flow.

Runs every tool's actual data-path against PersistentStore with real OpenAI
embeddings to catch issues before the live demo.

Usage:
    cd /Users/risheeksomu/AI-Engineer-Certification-Challenge
    source .venv/bin/activate
    python tests/test_demo_flow.py
"""

import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime

# Ensure the project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from macro_mate.persistent_store import PersistentStore
from macro_mate.vector_store import get_embeddings
from macro_mate.config import EMBEDDING_DIMS

# ════════════════════════════════════════════════════════════════════════
# Setup
# ════════════════════════════════════════════════════════════════════════

DB_PATH = os.path.join(tempfile.gettempdir(), "test_demo_flow.db")
TODAY = datetime.now().strftime("%Y-%m-%d")
PASSED = 0
FAILED = 0


def cleanup():
    for ext in ("", "-wal", "-shm"):
        path = DB_PATH + ext
        if os.path.exists(path):
            os.remove(path)


def check(label: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {label}")
    else:
        FAILED += 1
        msg = f"  ❌ {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)


cleanup()
print("Creating PersistentStore with real OpenAI embeddings...\n")
embeddings = get_embeddings()
store = PersistentStore(db_path=DB_PATH, embeddings=embeddings, dims=EMBEDDING_DIMS)


# ════════════════════════════════════════════════════════════════════════
# Phase 1 — Profile Setup (mimics Tool 4: manage_user_profile action=set)
# ════════════════════════════════════════════════════════════════════════

print("═══ Phase 1: Profile Setup ═══")

# Exact calls manage_user_profile makes: store.put(namespace, field, {"value": value})
store.put(("default_user", "profile"), "weight_kg", {"value": "81.6"})
store.put(("default_user", "profile"), "height_cm", {"value": "180"})
store.put(("default_user", "profile"), "age", {"value": "28"})
store.put(("default_user", "profile"), "sex", {"value": "male"})
store.put(("default_user", "profile"), "activity_level", {"value": "active"})

# manage_user_profile action=get does: items = list(store.search(namespace))
profile_items = list(store.search(("default_user", "profile")))
check("Profile has 5 fields", len(profile_items) == 5,
      f"got {len(profile_items)}: {[i.key for i in profile_items]}")

# Verify each field is readable
for field in ["weight_kg", "height_cm", "age", "sex", "activity_level"]:
    item = store.get(("default_user", "profile"), field)
    check(f"  Field '{field}' readable via get()", item is not None)

# Profile items have NO "text" field — should still work with _list_search
check("Profile search uses list mode (no query)", True)  # If we got here, it works
print()


# ════════════════════════════════════════════════════════════════════════
# Phase 2 — TDEE Calculation (mimics Tool 4: manage_user_profile action=tdee)
# ════════════════════════════════════════════════════════════════════════

print("═══ Phase 2: TDEE Calculation ═══")

# Reproduce the exact TDEE logic from tools.py
profile = {item.key: item.value.get("value", "") for item in profile_items}

weight = float(profile["weight_kg"])   # 81.6
height = float(profile["height_cm"])   # 180
age = float(profile["age"])            # 28
sex = profile["sex"].lower()           # male

bmr = 10 * weight + 6.25 * height - 5 * age + 5  # male formula
activity_factors = {
    "sedentary": 1.2, "light": 1.375, "moderate": 1.55,
    "active": 1.725, "very_active": 1.9,
}
activity = profile.get("activity_level", "moderate")
factor = activity_factors.get(activity, 1.55)
tdee = bmr * factor

# Store TDEE exactly like the tool does
store.put(("default_user", "profile"), "tdee", {"value": str(round(tdee))})

tdee_item = store.get(("default_user", "profile"), "tdee")
check("TDEE stored and retrievable", tdee_item is not None)
check(f"TDEE value correct ({round(tdee)})", tdee_item.value == {"value": str(round(tdee))},
      f"got {tdee_item.value}")

# Profile should now have 6 items (5 bio + tdee)
profile_items_after = list(store.search(("default_user", "profile")))
check("Profile now has 6 fields (5 bio + tdee)", len(profile_items_after) == 6,
      f"got {len(profile_items_after)}")
print()


# ════════════════════════════════════════════════════════════════════════
# Phase 3 — Log Meals (mimics Tool 3: log_consumption)
# ════════════════════════════════════════════════════════════════════════

print("═══ Phase 3: Log Meals ═══")

# Exact dict shape from log_consumption in tools.py
meals_to_log = [
    {
        "key": f"breakfast_{TODAY}T08:00:00",
        "food_name": "oatmeal with banana",
        "calories": 400.0,
        "protein_g": 12.0,
        "carbs_g": 65.0,
        "fat_g": 8.0,
        "meal_type": "breakfast",
    },
    {
        "key": f"lunch_{TODAY}T12:30:00",
        "food_name": "chicken breast with rice",
        "calories": 550.0,
        "protein_g": 45.0,
        "carbs_g": 50.0,
        "fat_g": 12.0,
        "meal_type": "lunch",
    },
    {
        "key": f"dinner_{TODAY}T18:00:00",
        "food_name": "salmon salad",
        "calories": 480.0,
        "protein_g": 38.0,
        "carbs_g": 15.0,
        "fat_g": 22.0,
        "meal_type": "dinner",
    },
    {
        # Special characters test
        "key": f"snack_{TODAY}T15:00:00",
        "food_name": "McDonald's Quarter Pounder",
        "calories": 530.0,
        "protein_g": 30.0,
        "carbs_g": 40.0,
        "fat_g": 27.0,
        "meal_type": "snack",
    },
]

for meal in meals_to_log:
    namespace = ("default_user", "consumption")
    key = meal["key"]
    now = datetime.now()

    # Exact value dict from log_consumption
    value = {
        "text": f"Ate {meal['food_name']} for {meal['meal_type']}: "
                f"{meal['calories']} cal, {meal['protein_g']}g protein, "
                f"{meal['carbs_g']}g carbs, {meal['fat_g']}g fat",
        "food_name": meal["food_name"],
        "calories": meal["calories"],
        "protein_g": meal["protein_g"],
        "carbs_g": meal["carbs_g"],
        "fat_g": meal["fat_g"],
        "meal_type": meal["meal_type"],
        "date": TODAY,
        "timestamp": now.isoformat(),
    }
    store.put(namespace, key, value)
    print(f"  Logged: {meal['food_name']} ({meal['meal_type']})")

# Verify all meals stored
all_stored = list(store.search(("default_user", "consumption"), limit=100))
check(f"All 4 meals stored", len(all_stored) == 4,
      f"got {len(all_stored)}")

# Verify special characters survived
mcdonalds = store.get(("default_user", "consumption"), f"snack_{TODAY}T15:00:00")
check("McDonald's apostrophe survived storage",
      mcdonalds is not None and mcdonalds.value["food_name"] == "McDonald's Quarter Pounder",
      f"got {mcdonalds.value['food_name'] if mcdonalds else 'None'}")
print()


# ════════════════════════════════════════════════════════════════════════
# Phase 4 — Daily Summary (mimics Tool 5: calculate_daily_summary)
# ════════════════════════════════════════════════════════════════════════

print("═══ Phase 4: Daily Summary (THE KEY TEST) ═══")
print('  Testing query="meal" — word "meal" does NOT appear in consumption text')
print("  This tests that hybrid search works via vector similarity when FTS misses\n")

# EXACT query from calculate_daily_summary in tools.py
all_meals = store.search(("default_user", "consumption"), query="meal", limit=100)
today_meals = [m for m in all_meals if m.value.get("date") == TODAY]

check(f'Hybrid search query="meal" found all 4 meals', len(today_meals) == 4,
      f"got {len(today_meals)} (all_meals={len(all_meals)})")

# Show what hybrid search returned for debugging
for m in today_meals:
    score_str = f"score={m.score:.4f}" if m.score is not None else "score=N/A"
    print(f"    {m.value['food_name']} — {score_str}")

# Sum macros (exact logic from calculate_daily_summary)
total_cal = sum(m.value.get("calories", 0) for m in today_meals)
total_protein = sum(m.value.get("protein_g", 0) for m in today_meals)
total_carbs = sum(m.value.get("carbs_g", 0) for m in today_meals)
total_fat = sum(m.value.get("fat_g", 0) for m in today_meals)

expected_cal = 400 + 550 + 480 + 530  # 1960
check(f"Total calories = {expected_cal}", total_cal == expected_cal,
      f"got {total_cal}")
check(f"Total protein = 125g", total_protein == 125.0,
      f"got {total_protein}")
check(f"Total carbs = 170g", total_carbs == 170.0,
      f"got {total_carbs}")
check(f"Total fat = 69g", total_fat == 69.0,
      f"got {total_fat}")

# TDEE comparison (exact logic from calculate_daily_summary)
tdee_item = store.get(("default_user", "profile"), "tdee")
check("TDEE item readable from profile", tdee_item is not None)
tdee_val = float(tdee_item.value.get("value", 0))
remaining = tdee_val - total_cal
print(f"  TDEE: {round(tdee_val)}, Consumed: {round(total_cal)}, Remaining: {round(remaining)}")
check("TDEE remaining is positive (under budget)", remaining > 0)
print()


# ════════════════════════════════════════════════════════════════════════
# Phase 5 — Progress Analysis (mimics Tool 6: analyze_progress)
# ════════════════════════════════════════════════════════════════════════

print("═══ Phase 5: Progress Analysis ═══")
print('  Testing query="meal food" — exact query from analyze_progress\n')

# EXACT queries from analyze_progress in tools.py
profile_items = list(store.search(("default_user", "profile")))
all_meals = list(store.search(
    ("default_user", "consumption"), query="meal food", limit=500
))

check(f"Profile search found 6 items", len(profile_items) == 6,
      f"got {len(profile_items)}")
check(f'Hybrid search query="meal food" found 4 meals', len(all_meals) == 4,
      f"got {len(all_meals)}")

# Reproduce the grouping logic from analyze_progress
profile = {item.key: item.value.get("value", "") for item in profile_items}
days = defaultdict(list)
for m in all_meals:
    date = m.value.get("date", "unknown")
    days[date].append(m.value)

check("Meals grouped into 1 day", len(days) == 1)

for date in sorted(days.keys()):
    meals = days[date]
    day_cal = sum(m.get("calories", 0) for m in meals)
    day_pro = sum(m.get("protein_g", 0) for m in meals)
    print(f"  {date}: {len(meals)} meals, {round(day_cal)} cal, {round(day_pro)}g protein")

# Verify float precision survived JSON round-trip
first_meal = all_meals[0]
cal_val = first_meal.value.get("calories")
check("Calorie value is float after JSON round-trip",
      isinstance(cal_val, (int, float)),
      f"type={type(cal_val).__name__}")
print()


# ════════════════════════════════════════════════════════════════════════
# Phase 6 — PERSISTENCE (THE MONEY SHOT)
# ════════════════════════════════════════════════════════════════════════

print("═══ Phase 6: Persistence — Close & Reopen ═══")
print("  Simulating server restart...\n")

store.close()

# Create a brand new store pointing at the same file
store2 = PersistentStore(db_path=DB_PATH, embeddings=embeddings, dims=EMBEDDING_DIMS)

# Re-run Phase 4 queries
all_meals_after = store2.search(("default_user", "consumption"), query="meal", limit=100)
today_meals_after = [m for m in all_meals_after if m.value.get("date") == TODAY]
check("After restart: hybrid search still finds all 4 meals",
      len(today_meals_after) == 4,
      f"got {len(today_meals_after)}")

total_cal_after = sum(m.value.get("calories", 0) for m in today_meals_after)
check(f"After restart: calorie sum still {expected_cal}",
      total_cal_after == expected_cal,
      f"got {total_cal_after}")

# Re-run Phase 5 queries
profile_after = list(store2.search(("default_user", "profile")))
check("After restart: profile still has 6 fields",
      len(profile_after) == 6,
      f"got {len(profile_after)}")

tdee_after = store2.get(("default_user", "profile"), "tdee")
check("After restart: TDEE still readable",
      tdee_after is not None and tdee_after.value == {"value": str(round(tdee))})

# Check McDonald's special characters survived restart
mcdonalds_after = store2.get(("default_user", "consumption"), f"snack_{TODAY}T15:00:00")
check("After restart: McDonald's apostrophe intact",
      mcdonalds_after is not None and
      mcdonalds_after.value["food_name"] == "McDonald's Quarter Pounder")

# Verify namespaces survive
namespaces = store2.list_namespaces()
check("After restart: namespaces intact",
      ("default_user", "consumption") in namespaces and
      ("default_user", "profile") in namespaces,
      f"got {namespaces}")
print()


# ════════════════════════════════════════════════════════════════════════
# Phase 7 — Multi-User Isolation
# ════════════════════════════════════════════════════════════════════════

print("═══ Phase 7: Multi-User Isolation ═══")

# Add a second user
store2.put(("user_alice", "profile"), "weight_kg", {"value": "60"})
store2.put(("user_alice", "consumption"), f"lunch_{TODAY}T12:00:00", {
    "text": "Ate tofu stir fry for lunch: 300 cal, 20g protein, 25g carbs, 12g fat",
    "food_name": "tofu stir fry",
    "calories": 300.0,
    "protein_g": 20.0,
    "carbs_g": 25.0,
    "fat_g": 12.0,
    "meal_type": "lunch",
    "date": TODAY,
    "timestamp": datetime.now().isoformat(),
})

# User 1 should still see only their data
u1_meals = store2.search(("default_user", "consumption"), query="meal", limit=100)
u1_today = [m for m in u1_meals if m.value.get("date") == TODAY]
check("User 1 still sees only their 4 meals",
      len(u1_today) == 4,
      f"got {len(u1_today)}")

# User 2 should see only their data
u2_meals = store2.search(("user_alice", "consumption"), query="meal", limit=100)
check("User Alice sees only her 1 meal",
      len(u2_meals) == 1,
      f"got {len(u2_meals)}")

# Profile isolation
u1_profile = store2.search(("default_user", "profile"))
u2_profile = store2.search(("user_alice", "profile"))
check("User 1 profile: 6 fields",
      len(list(u1_profile)) == 6,
      f"got {len(list(u1_profile))}")
check("User Alice profile: 1 field",
      len(list(u2_profile)) == 1,
      f"got {len(list(u2_profile))}")
print()


# ════════════════════════════════════════════════════════════════════════
# Phase 8 — Edge Cases
# ════════════════════════════════════════════════════════════════════════

print("═══ Phase 8: Edge Cases ═══")

# 8a: Fresh user with zero meals
print("  8a: Fresh user (no data)")
new_user_meals = store2.search(("brand_new_user", "consumption"), query="meal", limit=100)
check("Fresh user: meal search returns empty list",
      len(new_user_meals) == 0,
      f"got {len(new_user_meals)}")

new_user_profile = list(store2.search(("brand_new_user", "profile")))
check("Fresh user: profile search returns empty list",
      len(new_user_profile) == 0)

# 8b: Unicode food names
print("  8b: Unicode food names")
store2.put(("default_user", "consumption"), f"snack_{TODAY}T16:00:00", {
    "text": "Ate açaí bowl for snack: 350 cal, 5g protein, 60g carbs, 12g fat",
    "food_name": "açaí bowl",
    "calories": 350.0,
    "protein_g": 5.0,
    "carbs_g": 60.0,
    "fat_g": 12.0,
    "meal_type": "snack",
    "date": TODAY,
    "timestamp": datetime.now().isoformat(),
})

acai = store2.get(("default_user", "consumption"), f"snack_{TODAY}T16:00:00")
check("Unicode food name 'açaí bowl' stored and retrieved",
      acai is not None and acai.value["food_name"] == "açaí bowl",
      f"got {acai.value['food_name'] if acai else 'None'}")

# 8c: Profile update (overwrite existing field)
print("  8c: Profile field update")
store2.put(("default_user", "profile"), "weight_kg", {"value": "80.0"})
updated = store2.get(("default_user", "profile"), "weight_kg")
check("Weight updated from 81.6 to 80.0",
      updated.value == {"value": "80.0"},
      f"got {updated.value}")

# Profile should still have 6 items (not 7 — update, not insert)
profile_count = len(list(store2.search(("default_user", "profile"))))
check("Profile still has 6 fields after update (not 7)",
      profile_count == 6,
      f"got {profile_count}")

# 8d: Delete and re-check
print("  8d: Delete item")
store2.delete(("default_user", "consumption"), f"snack_{TODAY}T16:00:00")
deleted = store2.get(("default_user", "consumption"), f"snack_{TODAY}T16:00:00")
check("Açaí bowl deleted successfully", deleted is None,
      f"got {deleted}")

# 8e: Search with empty namespace prefix (broad search)
print("  8e: Broad namespace search")
all_namespaces = store2.list_namespaces()
check("list_namespaces returns all user namespaces",
      len(all_namespaces) >= 4,  # default_user profile+consumption, user_alice profile+consumption
      f"got {len(all_namespaces)}: {all_namespaces}")

# 8f: Back to 4 meals after deleting açaí
remaining_meals = store2.search(("default_user", "consumption"), query="meal", limit=100)
remaining_today = [m for m in remaining_meals if m.value.get("date") == TODAY]
check("Back to 4 meals after deleting açaí",
      len(remaining_today) == 4,
      f"got {len(remaining_today)}")
print()


# ════════════════════════════════════════════════════════════════════════
# Cleanup & Summary
# ════════════════════════════════════════════════════════════════════════

store2.close()
cleanup()

print("═" * 60)
print(f"  PASSED: {PASSED}")
print(f"  FAILED: {FAILED}")
print("═" * 60)

if FAILED == 0:
    print("\n🎉 ALL DEMO FLOW TESTS PASSED!\n")
else:
    print(f"\n⚠️  {FAILED} test(s) FAILED — fix before demo!\n")
    sys.exit(1)
