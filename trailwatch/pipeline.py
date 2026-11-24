"""Ingest CSVs, validate readings, load clean rows into SQLite, log rejects."""
import csv
import datetime as dt
import math
import sqlite3
import sys
from pathlib import Path

from .clock import today as today_utc

LIMITS = {
    "temp_c": (-50, 45),
    "snow_depth_cm": (0, 1000),
    "wind_kph": (0, 250),
    "precip_mm": (0, 500),
}

SCHEMA = """
CREATE TABLE stations(station_id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL);
CREATE TABLE trails(trail_id TEXT PRIMARY KEY, name TEXT, region TEXT, station_id TEXT);
CREATE TABLE trail_points(trail_id TEXT, seq INTEGER, lat REAL, lon REAL, elev_m REAL,
                          PRIMARY KEY(trail_id, seq));
CREATE TABLE readings(station_id TEXT, date TEXT, temp_c REAL, snow_depth_cm REAL,
                      wind_kph REAL, precip_mm REAL, PRIMARY KEY(station_id, date));
CREATE TABLE rejected_readings(reason TEXT, raw TEXT);
"""


def _num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def validate_reading(row, station_ids, today=None):
    errors = []
    if row.get("station_id") not in station_ids:
        errors.append("unknown station")
    try:
        day = dt.date.fromisoformat(row.get("date", ""))
    except ValueError:
        errors.append("bad date")
    else:
        # A station cannot report tomorrow's weather. A clock skewed at the source, or a typo in
        # the year, used to load as the newest reading there is, which then outranked every real
        # one in "ORDER BY date DESC" and became the current conditions.
        if day > (today or today_utc()):
            errors.append("date in the future")
    for field, (lo, hi) in LIMITS.items():
        v = _num(row.get(field))
        if v is None:
            errors.append(f"missing {field}")
        elif not lo <= v <= hi:
            errors.append(f"{field} out of range")
    return errors


def _read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def run(data_dir="data", db_path="trailwatch.db"):
    data = Path(data_dir)
    db = Path(db_path)
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)

    stations = _read(data / "stations.csv")
    con.executemany("INSERT INTO stations VALUES(?,?,?,?)",
                    [(s["station_id"], s["name"], s["lat"], s["lon"]) for s in stations])
    trails = _read(data / "trails.csv")
    con.executemany("INSERT INTO trails VALUES(?,?,?,?)",
                    [(t["trail_id"], t["name"], t["region"], t["station_id"]) for t in trails])
    points = _read(data / "trail_points.csv")
    con.executemany("INSERT INTO trail_points VALUES(?,?,?,?,?)",
                    [(p["trail_id"], p["seq"], p["lat"], p["lon"], p["elev_m"]) for p in points])

    station_ids = {s["station_id"] for s in stations}
    loaded = rejected = 0
    seen = set()
    for row in _read(data / "readings.csv"):
        errors = validate_reading(row, station_ids)
        key = (row["station_id"], row["date"])
        if not errors and key in seen:
            errors.append("duplicate")
        if errors:
            con.execute("INSERT INTO rejected_readings VALUES(?,?)",
                        ("; ".join(errors), str(row)))
            rejected += 1
            continue
        seen.add(key)
        con.execute("INSERT INTO readings VALUES(?,?,?,?,?,?)",
                    (row["station_id"], row["date"], float(row["temp_c"]),
                     float(row["snow_depth_cm"]), float(row["wind_kph"]),
                     float(row["precip_mm"])))
        loaded += 1
    con.commit()
    con.close()
    return {"trails": len(trails), "points": len(points), "stations": len(stations),
            "readings_loaded": loaded, "readings_rejected": rejected}


if __name__ == "__main__":
    print(run(*sys.argv[1:3]))
