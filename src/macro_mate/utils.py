"""Shared utility functions for MacroMind."""


def calculate_tdee(
    weight_kg: float,
    height_cm: float,
    age: float,
    sex: str,
    activity_level: str,
) -> tuple[float, float]:
    """Calculate BMR and TDEE using the Mifflin-St Jeor equation.

    Returns:
        (bmr, tdee) tuple.
    """
    if sex.lower() == "male":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    activity_factors = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }
    factor = activity_factors.get(activity_level, 1.55)
    tdee = bmr * factor
    return bmr, tdee
