import sqlite3

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


def test_a_swapped_lat_and_lon_is_rejected(tmp_path):
    # 40.1,-111.1 written the wrong way round. Both halves are numbers, so only the range check
    # catches it, and without that the trail is drawn off the west coast of Africa.
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "trail_points.csv").write_text(
        "trail_id,seq,lat,lon,elev_m\nT1,1,40.1,-111.1,2000\nT1,2,-111.2,40.2,2100\n"
    )
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(data, tmp_path / "range1.db")
    message = str(caught.value)
    assert "trail_points.csv line 3" in message
    assert "outside the range -90.0 to 90.0" in message
    assert "wrong way round" in message


def test_a_station_outside_the_world_is_rejected(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "stations.csv").write_text("station_id,name,lat,lon\nS1,Alpha,40.1,-999\n")
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(data, tmp_path / "range2.db")
    assert "outside the range -180.0 to 180.0" in str(caught.value)


def test_the_edges_of_the_world_are_still_valid(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "trail_points.csv").write_text(
        "trail_id,seq,lat,lon,elev_m\nT1,1,-90,-180,0\nT1,2,90,180,0\n"
    )
    assert run(data, tmp_path / "range3.db")["points"] == 2


def test_the_committed_sample_data_passes_every_check():
    # The checks are worth nothing if the data shipped with the project cannot survive them.
    import tempfile
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        assert run(repo / "data", Path(tmp) / "sample.db")["trails"] > 0


def test_a_trail_listed_twice_is_named(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER + "T1,Ridge,North,S1\n")
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(data, tmp_path / "dup1.db")
    message = str(caught.value)
    assert "trails.csv line 3" in message
    assert "trail_id='T1' appears twice" in message


def test_a_station_listed_twice_is_named(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "stations.csv").write_text(
        "station_id,name,lat,lon\nS1,Alpha,40.1,-111.1\nS1,Alpha again,40.2,-111.2\n"
    )
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(data, tmp_path / "dup2.db")
    assert "station_id='S1' appears twice" in str(caught.value)


def test_a_repeated_point_in_one_trail_is_named(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "trail_points.csv").write_text(
        "trail_id,seq,lat,lon,elev_m\nT1,1,40.1,-111.1,2000\nT1,1,40.2,-111.2,2100\n"
    )
    with pytest.raises(pipeline_mod.DataError) as caught:
        run(data, tmp_path / "dup3.db")
    assert "trail_id='T1', seq=1 appears twice" in str(caught.value)


def test_the_same_sequence_number_under_another_trail_is_fine(tmp_path):
    # seq counts within a trail, so every trail starts again at 1. Only the pair has to be unique.
    data = _tiny_dataset(tmp_path / "data", HEADER + "T2,Creek,North,S1\n")
    (data / "trail_points.csv").write_text(
        "trail_id,seq,lat,lon,elev_m\n"
        "T1,1,40.1,-111.1,2000\nT1,2,40.2,-111.2,2100\n"
        "T2,1,40.3,-111.3,2200\nT2,2,40.4,-111.4,2300\n"
    )
    assert run(data, tmp_path / "dup4.db")["points"] == 4


def test_a_duplicate_row_never_touches_the_existing_database(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    db = tmp_path / "survives.db"
    run(data, db)
    before = db.read_bytes()

    (data / "trails.csv").write_text(HEADER + "T1,Ridge,North,S1\n")
    with pytest.raises(pipeline_mod.DataError):
        run(data, db)
    assert db.read_bytes() == before


def test_a_failure_during_the_load_keeps_the_previous_database(tmp_path, monkeypatch):
    # The header and key checks run before anything is written, so the only way to reach the
    # load and then fail is for the load itself to go wrong. Simulated here, because the point
    # is that an unforeseen failure is survivable too.
    data = _tiny_dataset(tmp_path / "data", HEADER)
    db = tmp_path / "atomic.db"
    run(data, db)
    before = db.read_bytes()

    def explode(*_args, **_kwargs):
        raise sqlite3.IntegrityError("something nobody predicted")

    monkeypatch.setattr(pipeline_mod, "_load", explode)
    with pytest.raises(sqlite3.IntegrityError):
        run(data, db)

    assert db.read_bytes() == before, "a failed load must not replace a working database"
    assert not (tmp_path / "atomic.db.building").exists(), "the half-built file must be cleaned up"


def test_a_successful_run_leaves_no_temporary_file(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    db = tmp_path / "clean.db"
    run(data, db)
    assert db.exists()
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".building")] == []


def test_a_rebuild_replaces_the_old_contents(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    db = tmp_path / "swap.db"
    assert run(data, db)["trails"] == 1

    (data / "trails.csv").write_text(HEADER + "T2,Creek,North,S1\n")
    assert run(data, db)["trails"] == 2
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM trails").fetchone()[0] == 2
    con.close()


def test_the_summary_breaks_the_rejections_down_by_reason(built):
    _, summary = built
    by_reason = summary["rejections_by_reason"]
    assert by_reason, "a rejection count with no breakdown says nothing about the cause"
    assert "unknown station" in by_reason
    assert "duplicate" in by_reason
    assert "date in the future" in by_reason
    # Every rejected row contributes at least one reason, and a row that failed twice adds two.
    assert sum(by_reason.values()) >= summary["readings_rejected"]


def test_one_row_failing_twice_is_counted_under_both_reasons(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "readings.csv").write_text(
        "station_id,date,temp_c,snow_depth_cm,wind_kph,precip_mm\n"
        "NOPE,2026-01-02,999,20,10,0\n"
    )
    summary = run(data, tmp_path / "why.db")
    assert summary["readings_rejected"] == 1
    assert summary["rejections_by_reason"] == {"unknown station": 1, "temp_c out of range": 1}


def test_clean_readings_produce_an_empty_breakdown(tmp_path):
    data = _tiny_dataset(tmp_path / "data", HEADER)
    (data / "readings.csv").write_text(
        "station_id,date,temp_c,snow_depth_cm,wind_kph,precip_mm\n"
        "S1,2026-01-02,-3,20,10,0\n"
    )
    summary = run(data, tmp_path / "ok.db")
    assert summary["readings_rejected"] == 0
    assert summary["rejections_by_reason"] == {}
