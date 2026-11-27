import sqlite3

from trailwatch.clock import today as today_utc


def test_health(client):
    assert client.get("/api/health").get_json()["status"] == "ok"


def test_list_trails(client):
    data = client.get("/api/trails").get_json()
    assert len(data) == 6
    for t in data:
        assert t["length_km"] > 3 and t["elevation_gain_m"] > 0
        assert t["rating"] in {"Good", "Fair", "Poor"}


def test_single_trail(client):
    t = client.get("/api/trails/T1").get_json()
    assert t["name"] == "Cedar Ridge Loop"


def test_missing_trail_404(client):
    assert client.get("/api/trails/NOPE").status_code == 404
    assert client.get("/api/trails/NOPE/geojson").status_code == 404


def test_geojson_shape(client):
    gj = client.get("/api/trails/T2/geojson").get_json()
    assert gj["geometry"]["type"] == "LineString"
    assert len(gj["geometry"]["coordinates"]) == 45


def test_map_page(client):
    assert b"leaflet" in client.get("/").data


def test_ratings_differ_across_trails(client):
    ratings = {t["trail_id"]: t["rating"] for t in client.get("/api/trails").get_json()}
    assert ratings["T1"] == "Good" and ratings["T2"] == "Good"
    assert ratings["T3"] == "Fair" and ratings["T4"] == "Fair"
    assert ratings["T5"] == "Poor" and ratings["T6"] == "Poor"


def test_a_trail_summary_says_when_its_reading_is_from(client):
    trail = client.get("/api/trails").get_json()[0]
    assert trail["as_of"] is not None
    assert trail["age_days"] >= 0


def test_a_stale_database_is_not_rated_good(tmp_path):
    import datetime as dt

    from trailwatch import generate_data, pipeline
    from trailwatch.api import create_app

    old = today_utc() - dt.timedelta(days=400)
    generate_data.generate(tmp_path / "data", end=old)
    db = tmp_path / "old.db"
    pipeline.run(tmp_path / "data", db)
    trails = create_app(str(db)).test_client().get("/api/trails").get_json()
    assert trails, "the fixture should still produce trails"
    assert {t["rating"] for t in trails} == {"Stale"}
    assert all(t["score"] is None for t in trails)
    assert all(t["age_days"] > 365 for t in trails)


def test_a_missing_database_explains_itself_instead_of_crashing(tmp_path):
    from trailwatch.api import create_app

    path = tmp_path / "not-built-yet.db"
    client = create_app(str(path)).test_client()
    for route in ("/api/health", "/api/trails", "/api/trails/T1"):
        response = client.get(route)
        assert response.status_code == 503, route
        assert "python -m trailwatch.pipeline" in response.get_json()["error"]
    assert not path.exists(), "opening the API must not leave an empty database behind"


def test_a_database_with_no_tables_says_the_same_thing(tmp_path):
    import sqlite3

    from trailwatch.api import create_app

    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()  # a real file, no schema
    response = create_app(str(path)).test_client().get("/api/trails")
    assert response.status_code == 503
    assert "python -m trailwatch.pipeline" in response.get_json()["error"]


def test_health_counts_the_trails_it_can_see(client):
    body = client.get("/api/health").get_json()
    assert body["status"] == "ok"
    assert body["trails"] == 6


class CountingConnection(sqlite3.Connection):
    """Counts the queries a request makes, so an N+1 cannot creep back in unnoticed."""

    count = 0

    def execute(self, *args):
        CountingConnection.count += 1
        return super().execute(*args)


def count_queries(monkeypatch, client, route):
    real = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda p, *a, **k: real(p, *a, factory=CountingConnection, **k))
    CountingConnection.count = 0
    client.get(route)
    return CountingConnection.count


def test_listing_trails_does_not_query_once_per_trail(built, monkeypatch):
    from trailwatch.api import create_app

    client = create_app(str(built[0])).test_client()
    trails = len(create_app(str(built[0])).test_client().get("/api/trails").get_json())
    assert trails == 6
    queries = count_queries(monkeypatch, client, "/api/trails")
    # Trails, their points, their readings. Not two more for every trail.
    assert queries == 3, f"{queries} queries for {trails} trails"


def test_one_trail_still_matches_what_the_list_says(client):
    listed = {t["trail_id"]: t for t in client.get("/api/trails").get_json()}
    for trail_id, from_list in listed.items():
        assert client.get(f"/api/trails/{trail_id}").get_json() == from_list


def test_one_request_returns_every_trail_with_its_shape(client):
    body = client.get("/api/trails.geojson").get_json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 6
    for f in body["features"]:
        assert f["geometry"]["type"] == "LineString"
        assert len(f["geometry"]["coordinates"]) > 2
        assert f["properties"]["rating"]
        assert "as_of" in f["properties"]


def test_the_collection_carries_a_bbox_in_geojson_order(client):
    body = client.get("/api/trails.geojson").get_json()
    west, south, east, north = body["bbox"]
    assert -180 <= west < east <= 180
    assert -90 <= south < north <= 90
    for f in body["features"]:
        for lon, lat, _ in f["geometry"]["coordinates"]:
            assert west <= lon <= east and south <= lat <= north


def test_the_collection_matches_the_list(client):
    listed = {t["trail_id"]: t for t in client.get("/api/trails").get_json()}
    body = client.get("/api/trails.geojson").get_json()
    assert {f["properties"]["trail_id"] for f in body["features"]} == set(listed)
    for f in body["features"]:
        assert f["properties"] == listed[f["properties"]["trail_id"]]


def test_the_map_asks_for_the_collection_once(client):
    page = client.get("/").get_data(as_text=True)
    assert "/api/trails.geojson" in page
    assert "/geojson" not in page.replace("/api/trails.geojson", "")
    assert "fitBounds" in page


def test_a_trail_whose_station_is_missing_says_so(tmp_path):
    from trailwatch import pipeline
    from trailwatch.api import create_app

    data = tmp_path / "data"
    data.mkdir()
    (data / "trails.csv").write_text("trail_id,name,region,station_id\nT1,Ridge,North,NOPE\n")
    (data / "stations.csv").write_text("station_id,name,lat,lon\nS1,Alpha,40.1,-111.1\n")
    (data / "trail_points.csv").write_text(
        "trail_id,seq,lat,lon,elev_m\nT1,1,40.1,-111.1,2000\nT1,2,40.2,-111.2,2100\n"
    )
    (data / "readings.csv").write_text("station_id,date,temp_c,snow_depth_cm,wind_kph,precip_mm\n")
    db = tmp_path / "orphan.db"
    pipeline.run(data, db)
    client = create_app(str(db)).test_client()

    listed = client.get("/api/trails").get_json()[0]
    assert listed["rating"] == "No station"
    assert listed["score"] is None
    assert "NOPE is not in stations.csv" in listed["reasons"][0]
    # The single-trail route and the collection agree with the list.
    assert client.get("/api/trails/T1").get_json() == listed
    feature = client.get("/api/trails.geojson").get_json()["features"][0]
    assert feature["properties"]["rating"] == "No station"


def test_a_station_that_exists_but_is_quiet_still_reads_no_data(client):
    # "No station" is a wrong id in trails.csv. "No data" is a station that has not reported.
    ratings = {t["rating"] for t in client.get("/api/trails").get_json()}
    assert "No station" not in ratings


def test_a_one_point_trail_is_left_out_of_the_collection(tmp_path):
    from trailwatch import pipeline
    from trailwatch.api import create_app

    data = tmp_path / "data"
    data.mkdir()
    (data / "trails.csv").write_text("trail_id,name,region,station_id\nT1,Stub,North,S1\nT2,Real,North,S1\n")
    (data / "stations.csv").write_text("station_id,name,lat,lon\nS1,Alpha,40.1,-111.1\n")
    (data / "trail_points.csv").write_text(
        "trail_id,seq,lat,lon,elev_m\nT1,1,40.1,-111.1,2000\nT2,1,40.1,-111.1,2000\nT2,2,40.2,-111.2,2100\n"
    )
    (data / "readings.csv").write_text("station_id,date,temp_c,snow_depth_cm,wind_kph,precip_mm\n")
    db = tmp_path / "stub.db"
    pipeline.run(data, db)
    client = create_app(str(db)).test_client()

    ids = [f["properties"]["trail_id"] for f in client.get("/api/trails.geojson").get_json()["features"]]
    assert ids == ["T2"], "a one-point LineString is not valid GeoJSON"
    # It is still listed, because the trail exists; it just has no line.
    assert {t["trail_id"] for t in client.get("/api/trails").get_json()} == {"T1", "T2"}
    stub = client.get("/api/trails/T1/geojson")
    assert stub.status_code == 422
    assert "only 1 point" in stub.get_json()["error"]


def test_every_line_in_the_collection_has_at_least_two_points(client):
    for f in client.get("/api/trails.geojson").get_json()["features"]:
        assert len(f["geometry"]["coordinates"]) >= 2


def test_stations_lists_each_one_with_its_newest_reading(client):
    stations = client.get("/api/stations").get_json()
    assert len(stations) == 3
    for s in stations:
        assert s["station_id"] and s["name"]
        assert s["readings"] > 0
        assert s["age_days"] >= 0
        assert s["reporting"] is True


def test_a_station_with_no_readings_is_not_reporting(tmp_path):
    from trailwatch import pipeline
    from trailwatch.api import create_app

    data = tmp_path / "data"
    data.mkdir()
    (data / "trails.csv").write_text("trail_id,name,region,station_id\nT1,Ridge,North,S1\n")
    (data / "stations.csv").write_text(
        "station_id,name,lat,lon\nS1,Alpha,40.1,-111.1\nS2,Quiet,40.2,-111.2\n"
    )
    (data / "trail_points.csv").write_text(
        "trail_id,seq,lat,lon,elev_m\nT1,1,40.1,-111.1,2000\nT1,2,40.2,-111.2,2100\n"
    )
    (data / "readings.csv").write_text("station_id,date,temp_c,snow_depth_cm,wind_kph,precip_mm\n")
    db = tmp_path / "quiet.db"
    pipeline.run(data, db)

    stations = {s["station_id"]: s for s in create_app(str(db)).test_client().get("/api/stations").get_json()}
    assert stations["S2"]["readings"] == 0
    assert stations["S2"]["latest_reading"] is None
    assert stations["S2"]["age_days"] is None
    assert stations["S2"]["reporting"] is False


def test_a_trail_names_the_station_its_rating_came_from(client):
    for trail in client.get("/api/trails").get_json():
        assert trail["station_id"]
        assert trail["station_name"]


def _empty_database(path):
    """A database with the right tables and nothing in them, which is what a dead load left."""
    import sqlite3

    from trailwatch.pipeline import SCHEMA

    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    return path


def test_health_calls_an_empty_database_a_failure(tmp_path):
    db = _empty_database(tmp_path / "empty.db")
    from trailwatch.api import create_app

    response = create_app(str(db)).test_client().get("/api/health")
    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "empty"
    assert body["trails"] == 0
    assert "trailwatch.pipeline" in body["error"], "it should say how to build one"


def test_health_reports_what_it_can_see(client):
    body = client.get("/api/health").get_json()
    assert body["status"] == "ok"
    assert body["trails"] > 0 and body["stations"] > 0 and body["readings"] > 0
    assert body["latest_reading"] is not None


def test_a_loaded_database_is_not_called_empty(client):
    assert client.get("/api/health").status_code == 200
