"""Nutrition data pipeline — structured extraction, fallback chain, and caching.

This module centralises all nutrition data handling so that tools return
structured, source-labeled data instead of freeform text. This directly
improves factual correctness by preventing the LLM from rounding,
approximating, or misinterpreting numbers.

Confidence tiers:
  Tier 1 — USDA FoodData Central (verified)
  Tier 2 — Local knowledge base or user-confirmed cache (verified)
  Tier 3 — Web search / Tavily (estimated)
  Tier 4 — LLM reasoning only (AI estimate)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════════

class NutritionData(TypedDict, total=False):
    food_name: str
    calories: float | None
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    fiber_g: float | None
    sugar_g: float | None
    sodium_mg: float | None
    serving_size: str
    source: str            # "usda", "local_kb", "web", "user_confirmed", "cache"
    confidence_tier: int   # 1–4


TIER_LABELS = {
    1: "✅ Verified (USDA)",
    2: "✅ Verified (Local DB)",
    3: "⚠️ Estimated (Web Search)",
    4: "⚠️ AI Estimate",
}


def get_tier_label(tier: int) -> str:
    """Return a human-readable confidence label for a tier number."""
    return TIER_LABELS.get(tier, f"Tier {tier}")


# ═══════════════════════════════════════════════════════════════════════════
# Extraction — USDA API response
# ═══════════════════════════════════════════════════════════════════════════

def extract_nutrition_from_usda(api_response: dict) -> list[NutritionData]:
    """Parse the USDA FoodData Central API response into structured data.

    Args:
        api_response: The JSON dict from the USDA /foods/search endpoint.

    Returns:
        A list of NutritionData dicts (one per food result).
    """
    foods = api_response.get("foods", [])
    results: list[NutritionData] = []

    for food in foods[:3]:
        data: NutritionData = {
            "food_name": food.get("description", "Unknown"),
            "calories": None,
            "protein_g": None,
            "carbs_g": None,
            "fat_g": None,
            "fiber_g": None,
            "sugar_g": None,
            "sodium_mg": None,
            "source": "usda",
            "confidence_tier": 1,
        }

        # Parse serving size
        serving = food.get("servingSize", "")
        serving_unit = food.get("servingSizeUnit", "")
        data["serving_size"] = (
            f"{serving}{serving_unit}" if serving else "100g"
        )

        # Extract nutrients
        for nutrient in food.get("foodNutrients", []):
            n_name = nutrient.get("nutrientName", "")
            n_value = nutrient.get("value")
            n_unit = nutrient.get("unitName", "")

            if n_value is None:
                continue

            if "Energy" in n_name and n_unit == "KCAL":
                data["calories"] = float(n_value)
            elif "Protein" in n_name:
                data["protein_g"] = float(n_value)
            elif "Carbohydrate" in n_name:
                data["carbs_g"] = float(n_value)
            elif n_name == "Total lipid (fat)":
                data["fat_g"] = float(n_value)
            elif "Fiber" in n_name:
                data["fiber_g"] = float(n_value)
            elif "Sugars, total" in n_name:
                data["sugar_g"] = float(n_value)
            elif "Sodium" in n_name:
                data["sodium_mg"] = float(n_value)

        results.append(data)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Extraction — freeform text (retriever output, web results)
# ═══════════════════════════════════════════════════════════════════════════

# Patterns for common nutrition formats in text
_CALORIE_PATTERNS = [
    re.compile(r"(?:calories?|energy|kcal)\s*[:\-–]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:kcal|calories?|cal\b)", re.IGNORECASE),
]
_PROTEIN_PATTERNS = [
    re.compile(r"protein\s*[:\-–]?\s*(\d+(?:\.\d+)?)\s*g", re.IGNORECASE),
    re.compile(r"(\d+(?:\.\d+)?)\s*g\s*protein", re.IGNORECASE),
]
_CARB_PATTERNS = [
    re.compile(r"(?:carbs?|carbohydrates?)\s*[:\-–]?\s*(\d+(?:\.\d+)?)\s*g", re.IGNORECASE),
    re.compile(r"(\d+(?:\.\d+)?)\s*g\s*(?:carbs?|carbohydrates?)", re.IGNORECASE),
]
_FAT_PATTERNS = [
    re.compile(r"(?:fat|total\s*lipid)\s*[:\-–]?\s*(\d+(?:\.\d+)?)\s*g", re.IGNORECASE),
    re.compile(r"(\d+(?:\.\d+)?)\s*g\s*fat", re.IGNORECASE),
]


def _find_first(patterns: list[re.Pattern], text: str) -> float | None:
    """Return the first numeric match from a list of regex patterns."""
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return float(match.group(1))
    return None


def extract_nutrition_from_text(
    text: str, source: str = "local_kb", tier: int = 2
) -> NutritionData | None:
    """Attempt to extract structured nutrition data from freeform text.

    Returns None if no numeric nutrition data could be parsed.
    """
    calories = _find_first(_CALORIE_PATTERNS, text)
    protein = _find_first(_PROTEIN_PATTERNS, text)
    carbs = _find_first(_CARB_PATTERNS, text)
    fat = _find_first(_FAT_PATTERNS, text)

    # Only return structured data if we found at least calories or 2+ macros
    found_count = sum(1 for v in [calories, protein, carbs, fat] if v is not None)
    if found_count < 2:
        return None

    return {
        "food_name": "",  # Caller should set this from context
        "calories": calories,
        "protein_g": protein,
        "carbs_g": carbs,
        "fat_g": fat,
        "fiber_g": None,
        "sugar_g": None,
        "sodium_mg": None,
        "serving_size": "as described",
        "source": source,
        "confidence_tier": tier,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Formatting — structured data → tool output string
# ═══════════════════════════════════════════════════════════════════════════

def format_nutrition_response(data: list[NutritionData]) -> str:
    """Format structured nutrition data into a string the LLM will faithfully
    reproduce. Uses (EXACT) markers and an explicit instruction to prevent
    the LLM from rounding or paraphrasing numbers.
    """
    if not data:
        return "No nutrition data available."

    sections = []
    for item in data:
        tier = item.get("confidence_tier", 4)
        tier_label = get_tier_label(tier)
        exact_tag = "(EXACT)" if tier <= 2 else "(ESTIMATED)"

        lines = [
            f"[{tier_label}]",
            f"Food: {item.get('food_name', 'Unknown')}",
            f"Serving: {item.get('serving_size', 'N/A')}",
        ]

        # Core macros
        if item.get("calories") is not None:
            lines.append(f"Calories: {item['calories']} kcal {exact_tag}")
        if item.get("protein_g") is not None:
            lines.append(f"Protein: {item['protein_g']}g {exact_tag}")
        if item.get("carbs_g") is not None:
            lines.append(f"Carbs: {item['carbs_g']}g {exact_tag}")
        if item.get("fat_g") is not None:
            lines.append(f"Fat: {item['fat_g']}g {exact_tag}")

        # Optional micros
        if item.get("fiber_g") is not None:
            lines.append(f"Fiber: {item['fiber_g']}g")
        if item.get("sugar_g") is not None:
            lines.append(f"Sugar: {item['sugar_g']}g")
        if item.get("sodium_mg") is not None:
            lines.append(f"Sodium: {item['sodium_mg']}mg")

        sections.append("\n".join(lines))

    result = "\n\n".join(sections)
    result += (
        "\n\nINSTRUCTION: Report these numbers EXACTLY as shown above. "
        "Do not round, approximate, or paraphrase the values."
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Caching — store and retrieve confirmed food data
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_food_name(name: str) -> str:
    """Normalize a food name for cache key consistency."""
    return name.lower().strip()


def cache_nutrition_data(
    store: BaseStore,
    food_name: str,
    data: NutritionData,
    user_id: str | None = None,
) -> None:
    """Cache confirmed nutrition data in the persistent store.

    Stores in the global cache (all users benefit). If user_id is provided,
    also stores in the user's personal cache.
    """
    normalized = _normalize_food_name(food_name)
    cache_value = {
        "text": (
            f"Nutrition data for {food_name}: "
            f"{data.get('calories', '?')} cal, "
            f"{data.get('protein_g', '?')}g protein, "
            f"{data.get('carbs_g', '?')}g carbs, "
            f"{data.get('fat_g', '?')}g fat"
        ),
        "food_name": food_name,
        "calories": data.get("calories"),
        "protein_g": data.get("protein_g"),
        "carbs_g": data.get("carbs_g"),
        "fat_g": data.get("fat_g"),
        "fiber_g": data.get("fiber_g"),
        "serving_size": data.get("serving_size", "as described"),
        "original_source": data.get("source", "unknown"),
        "original_tier": data.get("confidence_tier", 4),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }

    # Global cache — shared across users
    try:
        store.put(("global", "food_cache"), normalized, cache_value)
    except Exception as e:
        logger.warning(f"Failed to cache globally: {e}")

    # Per-user cache
    if user_id:
        try:
            store.put((user_id, "food_cache"), normalized, cache_value)
        except Exception as e:
            logger.warning(f"Failed to cache for user {user_id}: {e}")


def search_cache(
    store: BaseStore,
    query: str,
    user_id: str | None = None,
) -> NutritionData | None:
    """Search the food cache for a previously confirmed food item.

    Checks per-user cache first (if user_id provided), then global cache.
    Returns a NutritionData dict or None if no match found.
    """
    namespaces = []
    if user_id:
        namespaces.append((user_id, "food_cache"))
    namespaces.append(("global", "food_cache"))

    for namespace in namespaces:
        try:
            # Try exact key lookup first
            normalized = _normalize_food_name(query)
            item = store.get(namespace, normalized)
            if item and item.value.get("calories") is not None:
                return _cache_item_to_nutrition_data(item.value)

            # Fall back to semantic search
            results = list(store.search(namespace, query=query, limit=3))
            for result in results:
                if result.value.get("calories") is not None:
                    return _cache_item_to_nutrition_data(result.value)
        except Exception as e:
            logger.debug(f"Cache search failed for {namespace}: {e}")
            continue

    return None


def _cache_item_to_nutrition_data(value: dict) -> NutritionData:
    """Convert a cache store item value to a NutritionData dict."""
    return {
        "food_name": value.get("food_name", ""),
        "calories": value.get("calories"),
        "protein_g": value.get("protein_g"),
        "carbs_g": value.get("carbs_g"),
        "fat_g": value.get("fat_g"),
        "fiber_g": value.get("fiber_g"),
        "sugar_g": None,
        "sodium_mg": None,
        "serving_size": value.get("serving_size", "as described"),
        "source": "cache",
        "confidence_tier": 2,  # Cached data was previously confirmed
    }


# ═══════════════════════════════════════════════════════════════════════════
# Unified fallback chain
# ═══════════════════════════════════════════════════════════════════════════

def lookup_food_nutrition(
    query: str,
    store: BaseStore,
    usda_api_key: str,
    user_id: str | None = None,
) -> str:
    """Unified food nutrition lookup with graceful fallback chain.

    Tries sources in order of reliability:
      1. USDA exact match (Tier 1)
      2. USDA fuzzy match (Tier 1, noted as closest match)
      3. Per-user food cache (Tier 2)
      4. Global food cache (Tier 2)
      5. Tavily web search (Tier 3)
      6. No data found (Tier 4 — tells agent to estimate or ask user)

    Returns a formatted string with structured nutrition data and tier labels.
    """
    fallback_path: list[str] = []

    # ── Step 1 & 2: USDA lookup ──────────────────────────────────────
    if usda_api_key:
        try:
            import requests
            url = "https://api.nal.usda.gov/fdc/v1/foods/search"
            params = {
                "api_key": usda_api_key,
                "query": query,
                "pageSize": 3,
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            results = extract_nutrition_from_usda(data)

            if results:
                # Check for exact match (query words appear in food name)
                query_words = set(query.lower().split())
                for result in results:
                    name_words = set(result["food_name"].lower().split(",")[0].split())
                    if query_words & name_words:  # At least one word overlap
                        fallback_path.append("USDA exact → matched")
                        # Cache the result for future lookups
                        cache_nutrition_data(store, query, result, user_id)
                        formatted = format_nutrition_response([result])
                        return (
                            f"[Source: USDA FoodData Central | "
                            f"Path: {' → '.join(fallback_path)}]\n\n"
                            + formatted
                        )

                # No exact match — use top result as fuzzy match
                fallback_path.append("USDA exact → miss")
                fallback_path.append("USDA fuzzy → matched (closest result)")
                top = results[0]
                cache_nutrition_data(store, query, top, user_id)
                formatted = format_nutrition_response(results[:2])
                return (
                    f"[Source: USDA FoodData Central (closest match) | "
                    f"Path: {' → '.join(fallback_path)}]\n"
                    f"Note: No exact match for '{query}'. "
                    f"Showing closest USDA results.\n\n"
                    + formatted
                )
            else:
                fallback_path.append("USDA → no results")
        except Exception as e:
            fallback_path.append(f"USDA → error ({type(e).__name__})")
            logger.warning(f"USDA lookup failed: {e}")
    else:
        fallback_path.append("USDA → no API key")

    # ── Step 3 & 4: Cache lookup ─────────────────────────────────────
    cached = search_cache(store, query, user_id)
    if cached:
        fallback_path.append("Cache → matched")
        formatted = format_nutrition_response([cached])
        return (
            f"[Source: Cached Data (previously confirmed) | "
            f"Path: {' → '.join(fallback_path)}]\n\n"
            + formatted
        )
    else:
        fallback_path.append("Cache → miss")

    # ── Step 5: Tavily web search ────────────────────────────────────
    try:
        from langchain_tavily import TavilySearch
        tavily = TavilySearch(max_results=3, topic="general")
        response = tavily.invoke(f"{query} nutrition facts calories protein carbs fat")

        if isinstance(response, list):
            web_results = response
        elif isinstance(response, dict):
            web_results = response.get("results", [])
        else:
            web_results = []

        if web_results:
            # Try to extract structured data from web results
            for r in web_results[:3]:
                content = r.get("content", str(r)) if isinstance(r, dict) else str(r)
                extracted = extract_nutrition_from_text(content, source="web", tier=3)
                if extracted:
                    extracted["food_name"] = query
                    fallback_path.append("Web search → matched (structured)")
                    cache_nutrition_data(store, query, extracted, user_id)
                    formatted = format_nutrition_response([extracted])
                    url = r.get("url", "N/A") if isinstance(r, dict) else "N/A"
                    return (
                        f"[Source: Web Search (Tavily) | "
                        f"Path: {' → '.join(fallback_path)}]\n"
                        f"URL: {url}\n\n"
                        + formatted
                    )

            # Web results found but no structured data extractable
            fallback_path.append("Web search → matched (unstructured)")
            formatted_web = []
            for i, r in enumerate(web_results[:3]):
                if isinstance(r, dict):
                    formatted_web.append(
                        f"[Web Source {i+1}]: {r.get('content', 'N/A')}\n"
                        f"URL: {r.get('url', 'N/A')}"
                    )
                else:
                    formatted_web.append(f"[Web Source {i+1}]: {str(r)}")

            return (
                f"[Source: Web Search (Tavily) — unstructured | "
                f"Path: {' → '.join(fallback_path)}]\n"
                f"[Confidence: Tier 3 - ⚠️ Estimated (Web Search)]\n"
                f"Could not extract exact macros. Raw results below:\n\n"
                + "\n\n".join(formatted_web)
                + "\n\nINSTRUCTION: These are web search results without "
                "verified nutrition data. If you estimate values from these "
                "results, clearly label them as '⚠️ AI Estimate'."
            )
        else:
            fallback_path.append("Web search → no results")
    except Exception as e:
        fallback_path.append(f"Web search → error ({type(e).__name__})")
        logger.warning(f"Tavily lookup failed: {e}")

    # ── Step 6: No data found ────────────────────────────────────────
    fallback_path.append("All sources exhausted")
    return (
        f"[Source: None — all lookups failed | "
        f"Path: {' → '.join(fallback_path)}]\n"
        f"[Confidence: Tier 4 - ⚠️ AI Estimate]\n\n"
        f"No verified nutrition data found for '{query}' in any source "
        f"(USDA, cache, or web search).\n\n"
        f"INSTRUCTION: If you provide any nutrition estimates for this food, "
        f"you MUST clearly label them as '⚠️ AI Estimate — not verified'. "
        f"Do not present AI estimates as facts."
    )
