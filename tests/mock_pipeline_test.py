from __future__ import annotations

"""Compatibility wrapper for legacy test imports.

New shared runtime/stub helpers live in ``mock_pipeline_runtime.py``.
Keep this module as a stable import surface while tests migrate.
"""

from mock_pipeline_runtime import *  # type: ignore F401,F403
