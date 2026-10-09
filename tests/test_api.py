def test_health(client):
    assert client.get("/api/health").get_json() == {"status": "ok"}


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
