"""Rule-based conditions score. Illustrative only, not a safety or avalanche tool."""
import datetime as dt

from .clock import today as today_utc

# Past this, a reading describes the weather of some other week. The score is about what the trail
# is like now, so beyond this the honest answer is that nobody knows, not a cheerful number from
# whenever the station last reported.
MAX_AGE_DAYS = 3

# A change in snow depth only means "recent accumulation" if the two readings bracketing it are
# close together. What the API passes is the newest few readings, which is not the same as the
# last few days: a station that reported in January and then went quiet until March hands over
# two readings three months apart, and comparing those called an entire winter's snowpack a
# rapid accumulation, with the same wording and the same penalty as 160 cm falling overnight.
SNOW_WINDOW_DAYS = 4


def _reading_date(reading):
    try:
        return dt.date.fromisoformat(reading.get("date", ""))
    except (TypeError, ValueError):
        return None


def _recent_accumulation(recent, as_of):
    """Depth gained since the oldest reading still close enough to the newest one to count.

    Readings with no usable date are skipped rather than assumed adjacent, and a window holding
    nothing but the newest reading yields no accumulation at all, which is the honest answer:
    one depth measurement says how much snow is lying, not how fast it arrived.
    """
    earliest_day = earliest = None
    for reading in recent[1:]:
        day = _reading_date(reading)
        if day is None or (as_of - day).days > SNOW_WINDOW_DAYS:
            continue
        if earliest_day is None or day < earliest_day:
            earliest_day, earliest = day, reading
    if earliest is None:
        return 0
    return recent[0]["snow_depth_cm"] - earliest["snow_depth_cm"]


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
    age = ((today or today_utc()) - as_of).days if as_of else None

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

    gain = _recent_accumulation(recent, as_of)
    if gain > 30:
        score -= 15
        reasons.append("rapid recent snow accumulation")

    score = max(0, score)
    rating = "Good" if score >= 75 else "Fair" if score >= 50 else "Poor"
    return {"score": score, "rating": rating, "reasons": reasons or ["no concerns"],
            "as_of": as_of.isoformat(), "age_days": age}
