import pytest

from trailwatch import pipeline as pipeline_mod
from trailwatch.clock import today as today_utc
from trailwatch.pipeline import run, validate_reading

OK = {
    "station_id": "ST1",
    "date": "2026-01-02",
    "temp_c": "-3",
    "snow_depth_cm": "20",
    "wind_kph": "10",
    "precip_mm": "0",
}


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
    row = {
        "station_id": "S1",
        "date": tomorrow,
        "temp_c": "0",
        "snow_depth_cm": "0",
        "wind_kph": "0",
        "precip_mm": "0",
    }
    assert validate_reading(row, {"S1"}) == ["date in the future"]


def test_todays_reading_is_still_accepted():

    row = {
        "station_id": "S1",
        "date": today_utc().isoformat(),
        "temp_c": "0",
        "snow_depth_cm": "0",
        "wind_kph": "0",
        "precip_mm": "0",
    }
    assert validate_reading(row, {"S1"}) == []


def test_the_future_check_can_be_pinned_to_a_date():
    import datetime as dt

    row = {
        "station_id": "S1",
        "date": "2026-06-02",
        "temp_c": "0",
        "snow_depth_cm": "0",
        "wind_kph": "0",
        "precip_mm": "0",
    }
    assert validate_reading(row, {"S1"}, today=dt.date(2026, 6, 1)) == ["date in the future"]
    assert validate_reading(row, {"S1"}, today=dt.date(2026, 6, 2)) == []


def test_the_generated_data_includes_a_future_dated_row_to_reject(built):
    _, summary = built
    assert summary["readings_rejected"] >= 7


def test_the_package_states_the_python_it_needs():
    import trailwatch

    assert trailwatch.MINIMUM_PYTHON == (3, 11)


def test_pyproject_declares_the_same_minimum():
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert pyproject["project"]["requires-python"] == ">=3.11"


def _tiny_dataset(folder, trails_text):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "trails.csv").write_text(trails_text, encoding="utf-8")
    (folder / "stations.csv").write_text("station_id,name,lat,lon\nS1,Alpha,40.1,-111.1\n")
    (folder / "trail_points.csv").write_text(
        "trail_id,seq,lat,lon,elev_m\nT1,1,40.1,-111.1,2000\nT1,2,40.2,-111.2,2100\n"
    )
    (folder / "readings.csv").write_text("station_id,date,temp_c,snow_depth_cm,wind_kph,precip_mm\n")
    return folder


HEADER = "trail_id,name,region,station_id\nT1,Ridge,North,S1\n"


def test_a_csv_saved_from_excel_loads(tmp_path):
    # Excel writes a byte order mark, which used to turn the first column name into "﻿trail_id".
    data = _tiny_dataset(tmp_path / "data", "﻿" + HEADER)
    summary = run(data, tmp_path / "x.db")
    assert summary["trails"] == 1


def test_a_plain_utf8_csv_still_loads(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    assert run(data, tmp_path / "y.db")["trails"] == 1


def test_non_ascii_names_survive_the_load(tmp_path):
    import sqlite3

    data = _tiny_dataset(tmp_path / "data", "trail_id,name,region,station_id\nT1,Cañón Ridge,North,S1\n")
    db = tmp_path / "z.db"
    run(data, db)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT name FROM trails").fetchone()[0] == "Cañón Ridge"
    con.close()


def test_a_missing_file_says_how_to_make_one(tmp_path):
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(tmp_path / "nothing-here", tmp_path / "a.db")
    assert "stations.csv is missing" in str(caught.value)
    assert "trailwatch.generate_data" in str(caught.value)


def test_a_renamed_column_is_named_with_the_header_that_was_found(tmp_path):
    data = _tiny_dataset(tmp_path / "data", "trail,name,region,station_id\nT1,Ridge,North,S1\n")
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(data, tmp_path / "b.db")
    message = str(caught.value)
    assert "no column named trail_id" in message
    assert "Its header is: trail, name, region, station_id" in message


def test_an_empty_file_says_it_is_empty(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "readings.csv").write_text("")
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(data, tmp_path / "c.db")
    assert "(the file is empty)" in str(caught.value)


def test_a_complete_header_loads(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    assert run(data, tmp_path / "d.db")["trails"] == 1


def test_a_trail_pointing_at_no_station_is_counted(tmp_path):
    data = _tiny_dataset(tmp_path / "data", "trail_id,name,region,station_id\nT1,Ridge,North,NOPE\n")
    assert run(data, tmp_path / "e.db")["trails_without_a_station"] == ["T1"]


def test_a_trail_with_a_real_station_is_not_counted(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    assert run(data, tmp_path / "f.db")["trails_without_a_station"] == []


def test_the_generated_data_has_no_orphan_trails(built):
    _, summary = built
    assert summary["trails_without_a_station"] == []


def test_a_trail_with_one_point_is_counted(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "trail_points.csv").write_text("trail_id,seq,lat,lon,elev_m\nT1,1,40.1,-111.1,2000\n")
    assert run(data, tmp_path / "g.db")["trails_without_a_line"] == ["T1"]


def test_a_trail_with_two_points_is_a_line(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    assert run(data, tmp_path / "h.db")["trails_without_a_line"] == []


def test_the_generated_trails_all_have_lines(built):
    _, summary = built
    assert summary["trails_without_a_line"] == []


def test_a_bad_input_leaves_the_existing_database_alone(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    db = tmp_path / "keep.db"
    assert run(data, db)["trails"] == 1
    before = db.read_bytes()

    (data / "trails.csv").write_text("trail,name,region,station_id\nT1,Ridge,North,S1\n")
    with pytest.raises(pipeline_mod.DataError):
        run(data, db)
    assert db.exists(), "a typo in a header must not delete a working database"
    assert db.read_bytes() == before


def test_a_failed_load_leaves_no_half_built_database(tmp_path):
    data = _tiny_dataset(tmp_path / "data", "trail,name,region,station_id\nT1,Ridge,North,S1\n")
    db = tmp_path / "never.db"
    with pytest.raises(pipeline_mod.DataError):
        run(data, db)
    assert not db.exists()


def test_a_latitude_that_is_not_a_number_is_named_with_its_line(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "trail_points.csv").write_text(
        "trail_id,seq,lat,lon,elev_m\nT1,1,40.1,-111.1,2000\nT1,2,N47.1,-111.2,2100\n"
    )
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(data, tmp_path / "num1.db")
    message = str(caught.value)
    assert "trail_points.csv line 3" in message
    assert "lat is 'N47.1'" in message


def test_a_sequence_number_that_is_not_whole_is_rejected(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "trail_points.csv").write_text(
        "trail_id,seq,lat,lon,elev_m\nT1,one,40.1,-111.1,2000\nT1,2,40.2,-111.2,2100\n"
    )
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(data, tmp_path / "num2.db")
    assert "seq is 'one', which is not a whole number" in str(caught.value)


def test_a_station_coordinate_that_is_not_a_number_is_rejected(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "stations.csv").write_text("station_id,name,lat,lon\nS1,Alpha,40.1,west\n")
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(data, tmp_path / "num3.db")
    assert "stations.csv line 2" in str(caught.value)


def test_coordinates_are_stored_as_numbers_not_text(tmp_path):
    # The point of the check above: what reaches the database has to be arithmetic-ready, because
    # the API does trigonometry on it long after the loader has finished.
    import sqlite3

    data = _tiny_dataset(tmp_path / "data", HEADER)
    db = tmp_path / "num4.db"
    run(data, db)
    con = sqlite3.connect(db)
    lat, seq = con.execute("SELECT lat, seq FROM trail_points LIMIT 1").fetchone()
    con.close()
    assert isinstance(lat, float) and isinstance(seq, int)
