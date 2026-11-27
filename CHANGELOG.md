# Changelog

All notable changes to Trailwatch are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `GET /api/rejects` returns the readings the loader threw away, counted by reason, with up to a
  hundred of the rows themselves. The `rejected_readings` table has been written since the first
  version of the pipeline and nothing has ever read it, so the only account of what was wrong with
  the input was a summary printed once into a terminal that is closed by the time anyone asks.
- The run summary carries `rejections_by_reason`. Seven rows rejected for one wrong station id is a
  two-minute fix; seven spread across six reasons is a different morning's work, and a single count
  cannot tell them apart.
- `GET /api/health` reports the station and reading counts and the date of the newest reading
  alongside the trail count, so a check that passes still says what it is passing on. A database
  full of trails with no readings at all is a distinct kind of broken, and the old answer had no
  way to say so.
- CI runs the tests on Python 3.12 and 3.13 as well as 3.11. `requires-python` claimed every
  version above the minimum and nothing tested one. Ruff moved to a job of its own, since it is
  pinned to a single target version and running it three times answered the same question
  three times.

### Fixed
- A coordinate that is not a number was loaded as text. SQLite's type affinity accepts it, the run
  reports success, and the first request that measures the trail hands a string to `math.radians`:
  a 500 for the whole of `/api/trails`, not for the one trail with the bad cell. Numeric columns are
  converted before anything is written, and a value that will not convert names its file, line
  and cell.
- A latitude and longitude written the wrong way round loaded without complaint, because both
  halves are valid numbers. The trail was simply drawn in the wrong hemisphere, which is worse than
  a refusal because nobody goes looking. Latitude is now held to -90..90 and longitude to -180..180.
- A row pasted twice in `stations.csv`, `trails.csv` or `trail_points.csv` came out as
  `sqlite3.IntegrityError: UNIQUE constraint failed`, which names a constraint and not a file, a
  line or an id. The three keys are checked in memory before the load, and the duplicate is named.
- A load that failed partway deleted the working database and left an empty one in its place. The
  new database is now built beside the old one and moved over it only on success. A move within one
  directory is atomic, so a reader sees the old database or the new one, never a half-written file.
- `GET /api/health` answered `{"status": "ok", "trails": 0}` to an empty database, which is exactly
  what a dead load used to leave behind and is indistinguishable from a region with no trails. No
  trails now means 503 and `"status": "empty"`, with the command that builds one.
- Snow accumulation was measured between the newest reading and the oldest one in the window,
  however far apart they were. A station reporting on 1 January and again on 1 March had three
  months of ordinary snowpack reported as "rapid recent snow accumulation", with the same wording
  and the same penalty as 160 cm falling overnight. The comparison now reaches back at most four
  days, skips readings with no usable date rather than assuming they are adjacent, and reports no
  accumulation when the window holds nothing else. The test covering this rule gave all four
  readings the same date, which readings from one station cannot have, which is why it never
  caught the problem.

## [0.1.0] - 2026-10-09

### Added
- CSV ingest with row-level validation and a `rejected_readings` table holding every bad row with
  its reason.
- Geospatial helpers: haversine distance, trail length, and elevation gain with a noise threshold
  for GPS wiggle.
- A rule-based conditions score over wind, temperature, precipitation and snow, with a staleness
  rule that refuses to rate readings more than three days old.
- Flask API and a Leaflet map, including a single GeoJSON FeatureCollection with a bbox so the map
  frames whatever region the data covers.
- CI with ruff and a 90% coverage gate.
