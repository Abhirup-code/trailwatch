from trailwatch.clock import today as today_utc
from trailwatch.pipeline import validate_reading

OK = {"station_id": "ST1", "date": "2026-01-02", "temp_c": "-3", "snow_depth_cm": "20",
      "wind_kph": "10", "precip_mm": "0"}


def test_valid_row_has_no_errors():
    assert validate_reading(OK, {"ST1"}) == []


def test_unknown_station():
    assert "unknown station" in validate_reading({**OK, "station_id": "X"}, {"ST1"})


def test_missing_value():
    assert "missing temp_c" in validate_reading({**OK, "temp_c": ""}, {"ST1"})


def test_out_of_range():
    assert "temp_c out of range" in validate_reading({**OK, "temp_c": "999"}, {"ST1"})


def test_negative_snow_rejected():
    assert "snow_depth_cm out of range" in validate_reading({**OK, "snow_depth_cm": "-5"}, {"ST1"})


def test_bad_date():
    assert "bad date" in validate_reading({**OK, "date": "nope"}, {"ST1"})


def test_pipeline_loads_and_rejects(built):
    _, s = built
    assert s["trails"] == 6 and s["stations"] == 3
    assert s["readings_loaded"] + s["readings_rejected"] == 3 * 30 + 3
    # 4 bad values, 1 duplicate, 1 unknown station, 1 dated after the window ends
    assert s["readings_rejected"] == 7


def test_a_reading_dated_in_the_future_is_rejected():
    import datetime as dt

    tomorrow = (today_utc() + dt.timedelta(days=1)).isoformat()
    row = {"station_id": "S1", "date": tomorrow, "temp_c": "0", "snow_depth_cm": "0",
           "wind_kph": "0", "precip_mm": "0"}
    assert validate_reading(row, {"S1"}) == ["date in the future"]


def test_todays_reading_is_still_accepted():

    row = {"station_id": "S1", "date": today_utc().isoformat(), "temp_c": "0",
           "snow_depth_cm": "0", "wind_kph": "0", "precip_mm": "0"}
    assert validate_reading(row, {"S1"}) == []


def test_the_future_check_can_be_pinned_to_a_date():
    import datetime as dt

    row = {"station_id": "S1", "date": "2026-06-02", "temp_c": "0", "snow_depth_cm": "0",
           "wind_kph": "0", "precip_mm": "0"}
    assert validate_reading(row, {"S1"}, today=dt.date(2026, 6, 1)) == ["date in the future"]
    assert validate_reading(row, {"S1"}, today=dt.date(2026, 6, 2)) == []


def test_the_generated_data_includes_a_future_dated_row_to_reject(built):
    _, summary = built
    assert summary["readings_rejected"] >= 7
