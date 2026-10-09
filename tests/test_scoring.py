from trailwatch.scoring import score_conditions


def day(temp=0, snow=30, wind=10, precip=0):
    return {"temp_c": temp, "snow_depth_cm": snow, "wind_kph": wind, "precip_mm": precip}


def test_calm_day_is_good():
    r = score_conditions([day()])
    assert r["score"] == 100 and r["rating"] == "Good"


def test_strong_wind_and_cold_is_poor_or_fair():
    r = score_conditions([day(temp=-20, wind=60)])
    assert r["score"] == 40 and r["rating"] == "Poor"
    assert "strong wind" in r["reasons"]


def test_rapid_snow_accumulation_flagged():
    r = score_conditions([day(snow=90), day(snow=70), day(snow=50), day(snow=40)])
    assert "rapid recent snow accumulation" in r["reasons"]


def test_no_data():
    assert score_conditions([])["rating"] == "No data"


def test_score_never_negative():
    r = score_conditions([day(temp=-30, wind=90, precip=40, snow=200), day(snow=0)])
    assert r["score"] >= 0
