"""Generate synthetic trails, stations and daily readings (deterministic).

All data is synthetic. Trail names and coordinates are invented.
Some readings are deliberately bad so the pipeline's validation has work to do.
"""
import csv
import datetime as dt
import math
import random
import sys
from pathlib import Path

from .clock import today as today_utc

TRAILS = [
    ("T1", "Cedar Ridge Loop", 40.690, -111.700, "ST1"),
    ("T2", "Granite Basin Trail", 40.610, -111.760, "ST1"),
    ("T3", "Aspen Hollow", 40.600, -111.640, "ST2"),
    ("T4", "Summit Saddle", 40.585, -111.630, "ST2"),
    ("T5", "Willow Creek Path", 40.660, -111.510, "ST3"),
    ("T6", "Ridgeline Traverse", 40.645, -111.490, "ST3"),
]
STATIONS = [
    ("ST1", "Canyon Base Station", 40.62, -111.78),
    ("ST2", "Alpine Pass Station", 40.59, -111.64),
    ("ST3", "High Valley Station", 40.65, -111.50),
]
DAYS = 30


def start_date(end=None):
    """The first day of the generated window, which ends on `end` (today by default).

    Generating a fixed window meant the committed data aged: every run of the demo was reading
    weather from whenever these constants were written, and the map rated it as current. Ending
    the window today keeps a freshly generated set usable, and makes the staleness of a stale one
    visible instead of silent.
    """
    return (end or today_utc()) - dt.timedelta(days=DAYS - 1)


def make_points(rng, lat, lon):
    bearing = rng.uniform(0, 360)
    elev = 1700 + rng.uniform(0, 400)
    slope = rng.uniform(5, 25)
    pts = []
    for seq in range(45):
        pts.append((seq, round(lat, 6), round(lon, 6), round(elev, 1)))
        step_km = 0.12
        lat += step_km * math.cos(math.radians(bearing)) / 111.0
        lon += step_km * math.sin(math.radians(bearing)) / (111.0 * math.cos(math.radians(lat)))
        bearing += rng.gauss(0, 12)
        elev = max(1000.0, elev + slope + rng.gauss(0, 4))
    return pts


def make_readings(rng, end=None):
    rows = []
    first = start_date(end)
    for sid, _, _, _ in STATIONS:
        offset = rng.uniform(-3, 3)
        depth = rng.uniform(20, 60)
        for d in range(DAYS):
            day = first + dt.timedelta(days=d)
            snowfall = rng.uniform(3, 25) if rng.random() < 0.3 else 0.0
            depth = max(0.0, depth + snowfall - 1.5)
            rows.append(
                {
                    "station_id": sid,
                    "date": day.isoformat(),
                    "temp_c": round(-4 + offset + 4 * math.sin(d / 4) + rng.gauss(0, 2), 1),
                    "snow_depth_cm": round(depth, 1),
                    "wind_kph": round(abs(rng.gauss(20, 14)), 1),
                    "precip_mm": round(snowfall * 0.1, 1),
                }
            )
    return apply_scenarios(rows)


def apply_scenarios(rows):
    """Force a calm station, a windy cold one and a storm so ratings differ."""
    def last_days(sid):
        return [r for r in rows if r["station_id"] == sid][-4:]

    for r in last_days("ST2"):
        r.update(temp_c=-12.0, wind_kph=55.0, precip_mm=0.0)
    for r, depth in zip(last_days("ST3"), (40.0, 55.0, 75.0, 95.0), strict=False):
        r.update(temp_c=-18.0, wind_kph=35.0, precip_mm=12.0, snow_depth_cm=depth)
    for r in last_days("ST1"):
        r.update(temp_c=-1.0, wind_kph=10.0, precip_mm=0.0)
    return rows


def inject_bad_rows(rng, rows, end=None):
    rows = list(rows)
    rows[5]["temp_c"] = ""
    rows[17]["temp_c"] = 999
    rows[40]["snow_depth_cm"] = -5
    rows[62]["wind_kph"] = 400
    rows.append(dict(rows[10]))  # exact duplicate of an earlier row
    # A reading dated after the window ends, the shape a skewed clock or a typed year produces.
    rows.append({"station_id": "ST1", "date": (start_date(end) + dt.timedelta(days=DAYS + 10)).isoformat(),
                 "temp_c": -2, "snow_depth_cm": 40, "wind_kph": 8, "precip_mm": 0})
    # A reading from a station that is not in stations.csv, so the pipeline has something to
    # reject. Dated inside the window so only the unknown station makes it invalid.
    rows.append({"station_id": "ST9", "date": (start_date(end) + dt.timedelta(days=4)).isoformat(),
                 "temp_c": -3, "snow_depth_cm": 10, "wind_kph": 12, "precip_mm": 0})
    return rows


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def generate(out_dir="data", seed=42, end=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    write_csv(out / "stations.csv", ["station_id", "name", "lat", "lon"], STATIONS)
    write_csv(
        out / "trails.csv",
        ["trail_id", "name", "region", "station_id"],
        [(t[0], t[1], "Wasatch (synthetic)", t[4]) for t in TRAILS],
    )
    pts = []
    for tid, _, lat, lon, _ in TRAILS:
        pts += [(tid, *p) for p in make_points(rng, lat, lon)]
    write_csv(out / "trail_points.csv", ["trail_id", "seq", "lat", "lon", "elev_m"], pts)
    readings = inject_bad_rows(rng, make_readings(rng, end), end)
    cols = ["station_id", "date", "temp_c", "snow_depth_cm", "wind_kph", "precip_mm"]
    write_csv(out / "readings.csv", cols, [[r[c] for c in cols] for r in readings])
    return out


if __name__ == "__main__":
    print("wrote", generate(sys.argv[1] if len(sys.argv) > 1 else "data"))
