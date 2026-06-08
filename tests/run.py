#!/usr/bin/env python3
"""Convenience runner: `python3 tests/run.py` -> runs the whole suite."""
import sys
import unittest
from pathlib import Path

loader = unittest.TestLoader()
suite = loader.discover(str(Path(__file__).resolve().parent), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
