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

    old = dt.date.today() - dt.timedelta(days=400)
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
