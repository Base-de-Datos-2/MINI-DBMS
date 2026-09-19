"""Shared Stage 9 fixtures: a prepared demo database and a live service."""

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.database import Database
from api.demo import PRESETS
from tests.api_helpers import open_service, small_demo


@pytest.fixture(scope="session")
def prepared_directory(tmp_path_factory):
    """One demo database created once, then only ever reopened read-only."""

    directory = tmp_path_factory.mktemp("demo")
    Database.create(small_demo(), directory).close()
    return directory


@pytest.fixture
def writable_directory(tmp_path):
    """A disposable demo database for tests that may write or break it."""

    Database.create(small_demo(), tmp_path).close()
    return tmp_path


@pytest.fixture(scope="module")
def service(prepared_directory):
    opened = open_service(prepared_directory)
    yield opened
    opened.close()


@pytest.fixture(scope="module")
def client(service):
    with TestClient(create_app(service, presets=PRESETS)) as test_client:
        yield test_client
