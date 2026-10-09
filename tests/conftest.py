import pytest

from trailwatch import generate_data, pipeline
from trailwatch.api import create_app


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("tw")
    generate_data.generate(root / "data")
    db = root / "t.db"
    summary = pipeline.run(root / "data", db)
    return db, summary


@pytest.fixture()
def client(built):
    return create_app(str(built[0])).test_client()
