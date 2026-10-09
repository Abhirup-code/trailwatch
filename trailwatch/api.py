"""Flask API and a Leaflet map page."""
import sqlite3
import sys

from flask import Flask, jsonify, g

from .geo import elevation_gain_m, trail_length_km
from .scoring import score_conditions

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Trailwatch</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>body{margin:0;font-family:system-ui,sans-serif}#map{height:100vh}
.legend{position:absolute;z-index:999;top:10px;right:10px;background:#fff;padding:8px 12px;border-radius:6px;font-size:13px}</style>
</head><body><div id="map"></div>
<div class="legend"><b>Trailwatch</b> (synthetic data)<br>Green Good, Orange Fair, Red Poor</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const colors = {Good: "#2e7d32", Fair: "#ef6c00", Poor: "#c62828"};
const map = L.map("map").setView([40.63, -111.62], 10);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  {attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
fetch("/api/trails").then(r => r.json()).then(trails => {
  trails.forEach(t => {
    fetch("/api/trails/" + t.trail_id + "/geojson").then(r => r.json()).then(gj => {
      const line = L.geoJSON(gj, {style: {color: colors[t.rating] || "#555", weight: 5}}).addTo(map);
      const box = document.createElement("div");
      const title = document.createElement("b"); title.textContent = t.name;
      box.appendChild(title);
      box.appendChild(document.createElement("br"));
      box.appendChild(document.createTextNode(
        t.length_km + " km, +" + t.elevation_gain_m + " m, " + t.rating + " (" + t.score + ")"));
      line.bindPopup(box);
    });
  });
});
</script></body></html>"""


def create_app(db_path="trailwatch.db"):
    app = Flask(__name__)

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(db_path)
            g.db.row_factory = sqlite3.Row
        return g.db

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

    def summary(trail):
        pts = points_for(trail["trail_id"])
        recent = [dict(r) for r in db().execute(
            "SELECT * FROM readings WHERE station_id=? ORDER BY date DESC LIMIT 4",
            (trail["station_id"],)).fetchall()]
        result = score_conditions(recent)
        return {
            "trail_id": trail["trail_id"],
            "name": trail["name"],
            "region": trail["region"],
            "length_km": round(trail_length_km(pts), 2),
            "elevation_gain_m": round(elevation_gain_m(pts)),
            "score": result["score"],
            "rating": result["rating"],
            "reasons": result["reasons"],
        }

    @app.get("/")
    def index():
        return PAGE

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/trails")
    def trails():
        rows = db().execute("SELECT * FROM trails ORDER BY trail_id").fetchall()
        return jsonify([summary(r) for r in rows])

    @app.get("/api/trails/<trail_id>")
    def trail(trail_id):
        row = db().execute("SELECT * FROM trails WHERE trail_id=?", (trail_id,)).fetchone()
        if row is None:
            return jsonify(error="trail not found"), 404
        return jsonify(summary(row))

    @app.get("/api/trails/<trail_id>/geojson")
    def geojson(trail_id):
        pts = points_for(trail_id)
        if not pts:
            return jsonify(error="trail not found"), 404
        return jsonify({
            "type": "Feature",
            "properties": {"trail_id": trail_id},
            "geometry": {"type": "LineString",
                         "coordinates": [[lon, lat, elev] for lat, lon, elev in pts]},
        })

    return app


if __name__ == "__main__":
    create_app(sys.argv[1] if len(sys.argv) > 1 else "trailwatch.db").run(port=5000)
