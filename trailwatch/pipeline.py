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


# Columns that have to hold a number. SQLite's type affinity stores a non-numeric string in a
# REAL column as text and says nothing about it, so a latitude written "N47.1" loaded cleanly and
# then failed inside math.radians on the first request that measured the trail. That is a 500 for
# the whole trail list rather than for the one trail, and nothing in the error names the file or
# the cell. Checking here turns it into a message that does.
NUMERIC_COLUMNS = {
    "stations.csv": {"lat": float, "lon": float},
    "trail_points.csv": {"seq": int, "lat": float, "lon": float, "elev_m": float},
}


# Being a number is not enough for a coordinate. The usual way to break one is to write the pair
# the wrong way round, and a longitude sitting in the latitude column is a perfectly good number,
# so the conversion above waves it through. Nothing then fails: the trail is simply drawn in the
# wrong hemisphere, and a map that is quietly wrong is worse than one that refuses to load.
COORDINATE_LIMITS = {"lat": (-90.0, 90.0), "lon": (-180.0, 180.0)}


def _numbers(path, rows):
    """Convert the numeric columns of one file in place, or name the cell that is wrong."""
    wanted = NUMERIC_COLUMNS.get(path.name, {})
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        for column, kind in wanted.items():
            try:
                row[column] = kind(row[column])
            except (TypeError, ValueError):
                want = "whole number" if kind is int else "number"
                raise DataError(
                    f"{path} line {line}: {column} is {row[column]!r}, which is not a {want}."
                ) from None
            limits = COORDINATE_LIMITS.get(column)
            if limits and not limits[0] <= row[column] <= limits[1]:
                raise DataError(
                    f"{path} line {line}: {column} is {row[column]}, outside the range "
                    f"{limits[0]} to {limits[1]}. A lat and lon written the wrong way round "
                    f"is the usual cause."
                )
    return rows


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
    return _numbers(path, rows)


def _unique(path, rows, columns):
    """Fail on a repeated key, naming it, rather than letting SQLite raise from inside the load.

    A row pasted twice is the commonest way a hand-edited CSV goes wrong, and the PRIMARY KEY
    declarations catch it either way. The difference is what the person sees: sqlite3 raises
    IntegrityError naming a constraint, which says nothing about which file or line to look at.
    """
    seen = set()
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        key = tuple(row[column] for column in columns)
        if key in seen:
            shown = ", ".join(f"{column}={row[column]!r}" for column in columns)
            raise DataError(
                f"{path} line {line}: {shown} appears twice. "
                f"Each {' and '.join(columns)} may appear only once in this file."
            )
        seen.add(key)


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

    # Readings are deliberately not checked here: a repeated reading is a row-level problem with
    # a reason and a place in rejected_readings, not a reason to abandon the whole load.
    _unique(data / "stations.csv", stations, ("station_id",))
    _unique(data / "trails.csv", trails, ("trail_id",))
    _unique(data / "trail_points.csv", points, ("trail_id", "seq"))

    # Build into a temporary file beside the target and move it into place only once the load has
    # finished. Deleting first meant any failure during the load, expected or not, left no working
    # database and an empty one in its place, which reads as a database with no trails in it
    # rather than as a failed run. The move is atomic within a directory, so a reader either sees
    # the previous database or the new one, never a half-written file.
    work = db.with_name(db.name + ".building")
    work.unlink(missing_ok=True)
    try:
        con = sqlite3.connect(work)
        try:
            summary = _load(con, stations, trails, points, readings)
        finally:
            con.close()
    except BaseException:
        work.unlink(missing_ok=True)
        raise
    work.replace(db)
    return summary


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
    # One number tells you something is wrong with the input and nothing about what. Forty rows
    # rejected for "unknown station" is one wrong id in one column; forty spread across six
    # reasons is a different morning's work. The reasons are counted individually, so a row that
    # failed twice is counted under both.
    reasons = Counter()
    seen = set()
    for row in readings:
        errors = validate_reading(row, station_ids)
        key = (row["station_id"], row["date"])
        if not errors and key in seen:
            errors.append("duplicate")
        if errors:
            con.execute("INSERT INTO rejected_readings VALUES(?,?)",
                        ("; ".join(errors), str(row)))
            reasons.update(errors)
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
            "rejections_by_reason": dict(reasons.most_common()),
            "trails_without_a_station": orphans, "trails_without_a_line": stubs}


if __name__ == "__main__":
    try:
        print(run(*sys.argv[1:3]))
    except DataError as problem:
        print(problem, file=sys.stderr)
        raise SystemExit(2) from None
