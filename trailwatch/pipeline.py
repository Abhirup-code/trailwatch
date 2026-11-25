"""Ingest CSVs, validate readings, load clean rows into SQLite, log rejects."""
import csv
import datetime as dt
import math
import sqlite3
import sys
from collections import Counter
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


class DataError(Exception):
    """A problem with the input files that no amount of row validation can work around."""


# Checked before anything is loaded. A row-level validator cannot report a missing column
# usefully: it sees None for every row and blames the data instead of the header.
REQUIRED_COLUMNS = {
    "stations.csv": ("station_id", "name", "lat", "lon"),
    "trails.csv": ("trail_id", "name", "region", "station_id"),
    "trail_points.csv": ("trail_id", "seq", "lat", "lon", "elev_m"),
    "readings.csv": ("station_id", "date", "temp_c", "snow_depth_cm", "wind_kph", "precip_mm"),
}


def _read(path):
    # utf-8-sig, not the platform default. Excel and Google Sheets write a byte order mark at the
    # start of a UTF-8 CSV, and csv.DictReader then reads the first column's name as "\ufefftrail_id",
    # so every lookup of "trail_id" fails with a bare KeyError that names a column plainly visible
    # in the file. Reading as utf-8-sig consumes the mark, and naming the encoding also stops the
    # load depending on whatever locale the machine happens to have.
    path = Path(path)
    if not path.exists():
        raise DataError(
            f"{path} is missing. Create the sample data with: "
            f"python -m trailwatch.generate_data {path.parent}"
        )
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames or []
    missing = [c for c in REQUIRED_COLUMNS.get(path.name, ()) if c not in header]
    if missing:
        raise DataError(
            f"{path} has no column named {', '.join(missing)}. "
            f"Its header is: {', '.join(header) if header else '(the file is empty)'}"
        )
    return rows


def run(data_dir="data", db_path="trailwatch.db"):
    data = Path(data_dir)
    db = Path(db_path)

    # Every input is read and checked before the old database is touched. Reading second meant a
    # typo in a header deleted a working database and then failed, leaving nothing at all, and
    # the connection opened just before it was never closed on the way out.
    stations = _read(data / "stations.csv")
    trails = _read(data / "trails.csv")
    points = _read(data / "trail_points.csv")
    readings = _read(data / "readings.csv")

    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    try:
        return _load(con, stations, trails, points, readings)
    finally:
        con.close()


def _load(con, stations, trails, points, readings):
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO stations VALUES(?,?,?,?)",
                    [(s["station_id"], s["name"], s["lat"], s["lon"]) for s in stations])
    con.executemany("INSERT INTO trails VALUES(?,?,?,?)",
                    [(t["trail_id"], t["name"], t["region"], t["station_id"]) for t in trails])
    con.executemany("INSERT INTO trail_points VALUES(?,?,?,?,?)",
                    [(p["trail_id"], p["seq"], p["lat"], p["lon"], p["elev_m"]) for p in points])

    station_ids = {s["station_id"] for s in stations}
    # A trail whose station is not in stations.csv can never be scored. It still belongs on the
    # map, so it is loaded, but it is counted here: silently showing "no data" forever hides a
    # typo in one column behind what looks like a quiet weather station.
    orphans = sorted(t["trail_id"] for t in trails if t["station_id"] not in station_ids)
    # One point is not a route: its length is zero, its climb is zero, and it cannot be drawn as
    # a line. Counted for the same reason as the orphans above, so a broken export is visible.
    counts = Counter(p["trail_id"] for p in points)
    stubs = sorted(t["trail_id"] for t in trails if counts[t["trail_id"]] < 2)
    loaded = rejected = 0
    seen = set()
    for row in readings:
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
    return {"trails": len(trails), "points": len(points), "stations": len(stations),
            "readings_loaded": loaded, "readings_rejected": rejected,
            "trails_without_a_station": orphans, "trails_without_a_line": stubs}


if __name__ == "__main__":
    try:
        print(run(*sys.argv[1:3]))
    except DataError as problem:
        print(problem, file=sys.stderr)
        raise SystemExit(2) from None
