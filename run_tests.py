"""
run_tests.py — Standalone Test Runner.

Executes all test functions in tests/ without requiring external test runners,
and also supports running via pytest: `pytest` or `python run_tests.py`.
"""

import importlib
import inspect
import sys
from pathlib import Path

# Provide lightweight pytest shim if pytest is not yet installed in environment
try:
    import pytest
except ImportError:
    class _DummyMark:
        @staticmethod
        def asyncio(fn):
            return fn

    class _DummyPytest:
        mark = _DummyMark()

        @staticmethod
        def fixture(*args, **kwargs):
            if len(args) == 1 and callable(args[0]):
                return args[0]
            def decorator(fn):
                return fn
            return decorator

    sys.modules["pytest"] = _DummyPytest()

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_all_tests():
    test_dir = PROJECT_ROOT / "tests"
    test_files = sorted(test_dir.glob("test_*.py"))

    total_run = 0
    total_passed = 0
    total_failed = 0
    failures = []

    print("=" * 65)
    print(" Free AI Job Application Agent — Test Suite Runner")
    print("=" * 65)

    for f in test_files:
        mod_name = f"tests.{f.stem}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:
            print(f"[FAIL] Could not import {mod_name}: {exc}")
            failures.append((mod_name, "IMPORT_ERROR", str(exc)))
            continue

        # Look for fixtures or helper factories
        fixtures = {}
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if callable(attr) and not attr_name.startswith("test_") and not attr_name.startswith("_"):
                try:
                    sig = inspect.signature(attr)
                    if len(sig.parameters) == 0:
                        fixtures[attr_name] = attr
                except Exception:
                    pass

        # Find test functions
        for attr_name in dir(mod):
            if attr_name.startswith("test_") and callable(getattr(mod, attr_name)):
                test_fn = getattr(mod, attr_name)
                sig = inspect.signature(test_fn)
                kwargs = {}
                for p in sig.parameters:
                    if p in fixtures:
                        kwargs[p] = fixtures[p]()
                    elif p == "sample_profile" and hasattr(mod, "sample_profile"):
                        kwargs[p] = mod.sample_profile()
                    elif p == "candidate_resume" and hasattr(mod, "candidate_resume"):
                        kwargs[p] = mod.candidate_resume()
                    elif p == "test_profile" and hasattr(mod, "test_profile"):
                        kwargs[p] = mod.test_profile()
                    elif p == "profile_1" and hasattr(mod, "profile_1"):
                        kwargs[p] = mod.profile_1()
                    elif p == "setup_test_db":
                        import tempfile
                        import config
                        from core.db import init_db
                        tmp = Path(tempfile.gettempdir()) / f"test_db_{total_run}.db"
                        config.DB_PATH = tmp
                        init_db()

                total_run += 1
                try:
                    test_fn(**kwargs)
                    print(f"  ✓ PASS: {f.stem} :: {attr_name}")
                    total_passed += 1
                except Exception as exc:
                    print(f"  ✗ FAIL: {f.stem} :: {attr_name} -> {exc}")
                    total_failed += 1
                    failures.append((f.stem, attr_name, str(exc)))

    print("=" * 65)
    print(f"Results: {total_passed} Passed, {total_failed} Failed, {total_run} Total")
    print("=" * 65)

    if failures:
        print("\nFailure Details:")
        for file, fn, err in failures:
            print(f"  - {file}.{fn}: {err}")
        sys.exit(1)
    else:
        print("\nAll automated tests passed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    run_all_tests()
