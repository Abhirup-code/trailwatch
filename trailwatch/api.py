"""Flask API and a Leaflet map page."""
import sqlite3
import sys

from flask import Flask, g, jsonify

from .geo import bounding_box, elevation_gain_m, trail_length_km
from .scoring import score_conditions

RECENT_DAYS = 4  # how many of the newest readings the score looks at
MIN_TRAIL_POINTS = 2  # a GeoJSON LineString needs two positions


class DatabaseUnavailable(RuntimeError):
    """Raised when the database cannot be opened, so the API can say what to do about it."""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Trailwatch</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>body{margin:0;font-family:system-ui,sans-serif}#map{height:100vh}
.legend{position:absolute;z-index:999;top:10px;right:10px;background:#fff;padding:8px 12px;border-radius:6px;font-size:13px}</style>
</head><body><div id="map"></div>
<div class="legend"><b>Trailwatch</b> (synthetic data)<br>Green Good, Orange Fair, Red Poor<br>Grey means the readings are too old to score</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const colors = {Good: "#2e7d32", Fair: "#ef6c00", Poor: "#c62828", Stale: "#9e9e9e", "No data": "#9e9e9e", "No station": "#9e9e9e"};
const map = L.map("map");
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  {attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
fetch("/api/trails.geojson").then(r => r.json()).then(gj => {
  const layer = L.geoJSON(gj, {
    style: f => ({color: colors[f.properties.rating] || "#555", weight: 5}),
    onEachFeature: (f, line) => {
      const t = f.properties;
      const box = document.createElement("div");
      const title = document.createElement("b"); title.textContent = t.name;
      box.appendChild(title);
      box.appendChild(document.createElement("br"));
      const rating = t.score === null ? t.rating : t.rating + " (" + t.score + ")";
      box.appendChild(document.createTextNode(
        t.length_km + " km, +" + t.elevation_gain_m + " m, " + rating));
      box.appendChild(document.createElement("br"));
      box.appendChild(document.createTextNode(
        t.as_of ? "reading from " + t.as_of + ", " + t.age_days + " days old" : "no readings"));
      line.bindPopup(box);
    },
  }).addTo(map);
  // Frame whatever the data covers, rather than a viewpoint written for one region.
  const b = layer.getBounds();
  if (b.isValid()) { map.fitBounds(b, {padding: [20, 20]}); } else { map.setView([0, 0], 2); }
});
</script></body></html>"""


def create_app(db_path="trailwatch.db"):
    app = Flask(__name__)

    def missing_db():
        return (
            f"No usable database at {db_path}. "
            f"Build one first: python -m trailwatch.pipeline data {db_path}"
        )

    def db():
        if "db" not in g:
            # mode=rw opens an existing file and refuses to invent one. The default would create
            # an empty database on the spot, so a typo in the path produced a 500 from the first
            # query and left a stray empty file behind, which then looked like a real database.
            try:
                g.db = sqlite3.connect(f"file:{db_path}?mode=rw", uri=True)
            except sqlite3.OperationalError as exc:
                raise DatabaseUnavailable(missing_db()) from exc
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.errorhandler(DatabaseUnavailable)
    def _unavailable(exc):
        return jsonify(error=str(exc)), 503

    @app.errorhandler(sqlite3.OperationalError)
    def _broken_db(_):
        # The file is there but the tables are not: an empty database left by an older version,
        # or a pipeline run that never finished.
        return jsonify(error=missing_db()), 503

    @app.teardown_appcontext
    def close_db(_):
        con = g.pop("db", None)
        if con is not None:
            con.close()

    def points_for(trail_id):
        rows = db().execute(
            "SELECT lat, lon, elev_m FROM trail_points WHERE trail_id=? ORDER BY seq",
            (trail_id,)).fetchall()
        return [(r["lat"], r["lon"], r["elev_m"]) for r in rows]

    def recent_for(station_id):
        return [dict(r) for r in db().execute(
            "SELECT * FROM readings WHERE station_id=? ORDER BY date DESC LIMIT ?",
            (station_id, RECENT_DAYS)).fetchall()]

    def known_trails():
        """Trails, each marked with whether its station actually exists."""
        return db().execute(
            "SELECT t.*, s.station_id IS NOT NULL AS station_known "
            "FROM trails t LEFT JOIN stations s ON s.station_id = t.station_id ORDER BY t.trail_id"
        ).fetchall()

    def all_points():
        """Every trail's points in one query, keyed by trail."""
        found = {}
        for r in db().execute("SELECT trail_id, lat, lon, elev_m FROM trail_points ORDER BY trail_id, seq"):
            found.setdefault(r["trail_id"], []).append((r["lat"], r["lon"], r["elev_m"]))
        return found

    def all_recent():
        """The newest RECENT_DAYS readings for every station in one query, keyed by station.

        The window function does per-station ranking in SQLite rather than issuing one LIMIT
        query per station, which is where most of the old query count came from.
        """
        found = {}
        rows = db().execute(
            "SELECT * FROM (SELECT *, ROW_NUMBER() OVER "
            "(PARTITION BY station_id ORDER BY date DESC) AS rn FROM readings) WHERE rn <= ?",
            (RECENT_DAYS,))
        for r in rows:
            row = dict(r)
            row.pop("rn", None)
            found.setdefault(row["station_id"], []).append(row)
        for readings in found.values():
            readings.sort(key=lambda r: r["date"], reverse=True)
        return found

    def _station_missing(trail):
        # sqlite3.Row raises IndexError for a column it does not have, and the single-trail and
        # collection queries both select the flag, so this only guards rows built in tests.
        try:
            return not trail["station_known"]
        except (IndexError, KeyError):
            return False

    def summary(trail, pts, recent):
        result = score_conditions(recent)
        # "No station" and "No data" look the same from outside and need opposite fixes: one is a
        # wrong station id in trails.csv, the other is a station that has not reported lately.
        if _station_missing(trail):
            result = {
                "score": None,
                "rating": "No station",
                "reasons": [f"station {trail['station_id']} is not in stations.csv"],
                "as_of": None,
                "age_days": None,
            }
        return {
            "trail_id": trail["trail_id"],
            "name": trail["name"],
            "region": trail["region"],
            "length_km": round(trail_length_km(pts), 2),
            "elevation_gain_m": round(elevation_gain_m(pts)),
            "score": result["score"],
            "rating": result["rating"],
            "reasons": result["reasons"],
            # When the reading is from, so a caller can see what the rating is based on rather
            # than assuming it is current.
            "as_of": result["as_of"],
            "age_days": result["age_days"],
        }

    @app.get("/")
    def index():
        return PAGE

    @app.get("/api/health")
    def health():
        # A health check that cannot fail is decoration. This one reads the database.
        trails = db().execute("SELECT COUNT(*) AS n FROM trails").fetchone()["n"]
        return jsonify(status="ok", trails=trails)

    @app.get("/api/trails")
    def trails():
        # Three queries whatever the number of trails: the trails, their points, their readings.
        rows = known_trails()
        points, readings = all_points(), all_recent()
        return jsonify([
            summary(r, points.get(r["trail_id"], []), readings.get(r["station_id"], []))
            for r in rows
        ])

    @app.get("/api/trails/<trail_id>")
    def trail(trail_id):
        row = db().execute(
            "SELECT t.*, s.station_id IS NOT NULL AS station_known "
            "FROM trails t LEFT JOIN stations s ON s.station_id = t.station_id WHERE t.trail_id=?",
            (trail_id,),
        ).fetchone()
        if row is None:
            return jsonify(error="trail not found"), 404
        return jsonify(summary(row, points_for(trail_id), recent_for(row["station_id"])))

    def feature(trail, pts, props):
        return {
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "LineString",
                         "coordinates": [[lon, lat, elev] for lat, lon, elev in pts]},
        }

    @app.get("/api/trails.geojson")
    def trails_geojson():
        """Every trail, its shape and its conditions, in one response.

        The map used to ask for the list and then fetch each trail's geometry separately, so a
        page load cost one request per trail. One FeatureCollection carries the lot, and its bbox
        lets the map frame whatever region the data covers instead of a hard-coded viewpoint.
        """
        rows = known_trails()
        points, readings = all_points(), all_recent()
        features, every_point = [], []
        for row in rows:
            pts = points.get(row["trail_id"], [])
            # A LineString needs two positions to be valid GeoJSON. One point is a trail that was
            # loaded wrong, and emitting it produces a document strict readers reject.
            if len(pts) < MIN_TRAIL_POINTS:
                continue
            every_point += pts
            features.append(feature(row, pts, summary(row, pts, readings.get(row["station_id"], []))))
        body = {"type": "FeatureCollection", "features": features}
        if every_point:
            south, west, north, east = bounding_box(every_point)
            body["bbox"] = [west, south, east, north]  # GeoJSON order, not ours
        return jsonify(body)

    @app.get("/api/trails/<trail_id>/geojson")
    def geojson(trail_id):
        pts = points_for(trail_id)
        if not pts:
            return jsonify(error="trail not found"), 404
        if len(pts) < MIN_TRAIL_POINTS:
            return jsonify(error=f"trail {trail_id} has only {len(pts)} point, so it has no line"), 422
        return jsonify(feature(None, pts, {"trail_id": trail_id}))

    return app


if __name__ == "__main__":
    create_app(sys.argv[1] if len(sys.argv) > 1 else "trailwatch.db").run(port=5000)
