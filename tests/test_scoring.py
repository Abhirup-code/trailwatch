import datetime as dt

from trailwatch.clock import today as today_utc
from trailwatch.scoring import MAX_AGE_DAYS, score_conditions

TODAY = dt.date(2026, 1, 10)


def day(temp=0, snow=30, wind=10, precip=0, date=TODAY):
    return {
        "date": date.isoformat(),
        "temp_c": temp,
        "snow_depth_cm": snow,
        "wind_kph": wind,
        "precip_mm": precip,
    }


def score(readings):
    return score_conditions(readings, today=TODAY)


def test_calm_day_is_good():
    r = score([day()])
    assert r["score"] == 100 and r["rating"] == "Good"
    assert r["as_of"] == "2026-01-10" and r["age_days"] == 0


def test_strong_wind_and_cold_is_poor_or_fair():
    r = score([day(temp=-20, wind=60)])
    assert r["score"] == 40 and r["rating"] == "Poor"
    assert "strong wind" in r["reasons"]


def test_rapid_snow_accumulation_flagged():
    r = score([day(snow=90), day(snow=70), day(snow=50), day(snow=40)])
    assert "rapid recent snow accumulation" in r["reasons"]


def test_no_data():
    r = score([])
    assert r["rating"] == "No data"
    assert r["as_of"] is None and r["age_days"] is None


def test_score_never_negative():
    r = score([day(temp=-30, wind=90, precip=40, snow=200), day(snow=0)])
    assert r["score"] >= 0


def test_a_reading_inside_the_window_is_still_scored():
    r = score([day(date=TODAY - dt.timedelta(days=MAX_AGE_DAYS))])
    assert r["rating"] == "Good"
    assert r["age_days"] == MAX_AGE_DAYS


def test_an_old_reading_is_reported_rather_than_scored():
    r = score([day(date=TODAY - dt.timedelta(days=MAX_AGE_DAYS + 1))])
    assert r["rating"] == "Stale"
    assert r["score"] is None
    assert r["reasons"] == [f"newest reading is {MAX_AGE_DAYS + 1} days old"]
    assert r["as_of"] == (TODAY - dt.timedelta(days=MAX_AGE_DAYS + 1)).isoformat()


def test_a_very_old_reading_is_not_quietly_good():
    # The exact case this exists for: a calm day from last winter.
    r = score([day(date=dt.date(2025, 1, 10))])
    assert r["rating"] == "Stale" and r["score"] is None


def test_a_reading_with_an_unusable_date_is_no_data():
    r = score([{"date": "not a date", "temp_c": 0, "snow_depth_cm": 0, "wind_kph": 0, "precip_mm": 0}])
    assert r["rating"] == "No data"
    assert "no usable date" in r["reasons"][0]


def test_staleness_is_measured_against_the_real_today_by_default():
    fresh = score_conditions([day(date=today_utc())])
    assert fresh["rating"] == "Good" and fresh["age_days"] == 0
