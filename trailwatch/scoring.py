"""Rule-based conditions score. Illustrative only, not a safety or avalanche tool."""
import datetime as dt

# Past this, a reading describes the weather of some other week. The score is about what the trail
# is like now, so beyond this the honest answer is that nobody knows, not a cheerful number from
# whenever the station last reported.
MAX_AGE_DAYS = 3


def _reading_date(reading):
    try:
        return dt.date.fromisoformat(reading.get("date", ""))
    except (TypeError, ValueError):
        return None


def score_conditions(recent, today=None):
    """recent: readings as dicts, newest first (up to 4 days).

    today: the date to measure staleness against, defaulting to the real one. Readings older than
    MAX_AGE_DAYS are reported as stale rather than scored, because a conditions tool that rates
    last winter's weather as "Good" today is worse than one that says nothing.
    """
    if not recent:
        return {"score": None, "rating": "No data", "reasons": ["no readings"],
                "as_of": None, "age_days": None}
    cur = recent[0]
    as_of = _reading_date(cur)
    age = ((today or dt.date.today()) - as_of).days if as_of else None

    if age is None:
        return {"score": None, "rating": "No data", "reasons": ["newest reading has no usable date"],
                "as_of": None, "age_days": None}
    if age > MAX_AGE_DAYS:
        days = "1 day" if age == 1 else f"{age} days"
        return {"score": None, "rating": "Stale",
                "reasons": [f"newest reading is {days} old"],
                "as_of": as_of.isoformat(), "age_days": age}

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
    return {"score": score, "rating": rating, "reasons": reasons or ["no concerns"],
            "as_of": as_of.isoformat(), "age_days": age}
