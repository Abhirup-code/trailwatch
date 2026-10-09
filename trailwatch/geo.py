"""Small geospatial helpers. Points are (lat, lon, elev_m) tuples."""
import math

EARTH_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def trail_length_km(points):
    return sum(
        haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:])
    )


def elevation_gain_m(points, noise_m=2.0):
    """Total climb, ignoring wiggles smaller than noise_m (GPS elevation is noisy)."""
    gain = 0.0
    ref = points[0][2] if points else 0.0
    for _, _, elev in points[1:]:
        if elev - ref >= noise_m:
            gain += elev - ref
            ref = elev
        elif ref - elev >= noise_m:
            ref = elev
    return gain


def bounding_box(points):
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return (min(lats), min(lons), max(lats), max(lons))
