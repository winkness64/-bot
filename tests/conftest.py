from __future__ import annotations

import asyncio

import pytest

from mock_pipeline_runtime import prepare_modules


@pytest.fixture
def mods() -> dict:
    return prepare_modules()


def run(coro):
    return asyncio.run(coro)
