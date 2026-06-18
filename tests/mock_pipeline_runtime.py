from __future__ import annotations

"""Shared test runtime/stub helpers.

Implementation is split under ``tests/fixtures`` to keep loader/stubs/fakes decoupled.
Keep this module as the stable import surface while tests migrate.
"""

from fixtures.mock_pipeline_fakes import *  # type: ignore F401,F403
from fixtures.mock_pipeline_loader import prepare_modules
from fixtures.mock_pipeline_stubs import *  # type: ignore F401,F403
