"""Tests decide with the structural stand-in at the Tev1 seam (Tev1 itself needs `uv sync --extra tev1`
and a 1.8 GB download; tests/test_tev1.py runs it when KG2A_TEST_TEV1=1)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("KG2A_DECIDER", "structural")
sys.path.insert(0, str(Path(__file__).parent))
