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
    assert s["readings_loaded"] + s["readings_rejected"] == 3 * 30 + 2
    assert s["readings_rejected"] == 6  # 4 bad values, 1 duplicate, 1 unknown station
