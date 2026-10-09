import pytest

from trailwatch.geo import bounding_box, elevation_gain_m, haversine_km, trail_length_km


def test_haversine_known_distance():
    # one degree of latitude is about 111.2 km
    assert haversine_km(40, -111, 41, -111) == pytest.approx(111.2, abs=0.3)


def test_haversine_zero():
    assert haversine_km(40, -111, 40, -111) == 0


def test_trail_length_sums_segments():
    pts = [(40, -111, 0), (40.01, -111, 0), (40.02, -111, 0)]
    assert trail_length_km(pts) == pytest.approx(2.22, abs=0.05)


def test_elevation_gain_ignores_noise():
    pts = [(0, 0, 100), (0, 0, 101), (0, 0, 100.5), (0, 0, 110)]
    assert elevation_gain_m(pts) == pytest.approx(10, abs=0.01)


def test_elevation_gain_ignores_descent():
    pts = [(0, 0, 200), (0, 0, 150), (0, 0, 120)]
    assert elevation_gain_m(pts) == 0


def test_bounding_box():
    assert bounding_box([(1, 5, 0), (3, 2, 0)]) == (1, 2, 3, 5)
