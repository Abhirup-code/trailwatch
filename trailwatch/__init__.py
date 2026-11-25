"""Trailwatch: outdoor conditions pipeline, scoring and map API (synthetic data)."""
import sys

# datetime.UTC is 3.11, itertools.pairwise is 3.10. Without this check, an older interpreter gets
# an AttributeError from somewhere inside clock.py or geo.py, which says nothing about the cause.
MINIMUM_PYTHON = (3, 11)

if sys.version_info < MINIMUM_PYTHON:
    need = ".".join(str(n) for n in MINIMUM_PYTHON)
    have = ".".join(str(n) for n in sys.version_info[:3])
    raise RuntimeError(f"Trailwatch needs Python {need} or newer. This is Python {have}.")
