"""Rule-based conditions score. Illustrative only, not a safety or avalanche tool."""


def score_conditions(recent):
    """recent: readings as dicts, newest first (up to 4 days)."""
    if not recent:
        return {"score": None, "rating": "No data", "reasons": ["no readings"]}
    cur = recent[0]
    score = 100
    reasons = []

    if cur["wind_kph"] > 50:
        score -= 35
        reasons.append("strong wind")
    elif cur["wind_kph"] > 30:
        score -= 15
        reasons.append("breezy")

    if cur["temp_c"] < -15:
        score -= 25
        reasons.append("very cold")
    elif cur["temp_c"] < -5:
        score -= 10
        reasons.append("cold")
    elif cur["temp_c"] > 30:
        score -= 15
        reasons.append("hot")

    if cur["precip_mm"] > 10:
        score -= 20
        reasons.append("heavy precipitation")
    elif cur["precip_mm"] > 2:
        score -= 8
        reasons.append("light precipitation")

    gain = cur["snow_depth_cm"] - recent[-1]["snow_depth_cm"] if len(recent) > 1 else 0
    if gain > 30:
        score -= 15
        reasons.append("rapid recent snow accumulation")

    score = max(0, score)
    rating = "Good" if score >= 75 else "Fair" if score >= 50 else "Poor"
    return {"score": score, "rating": rating, "reasons": reasons or ["no concerns"]}
