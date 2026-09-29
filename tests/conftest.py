import pytest

from research_cli.config import Settings
from research_cli.storage import Store
from research_cli.tools import Registry, register_files


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path)
    yield value
    value.close()


@pytest.fixture
def registry(store):
    value = Registry(store, Settings(api="demo"))
    register_files(value)
    return value


async def approve(name, args):
    return True


async def deny(name, args):
    return False
