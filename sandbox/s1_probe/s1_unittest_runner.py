"""Run one declared unittest target; print canonical JSON of each test's outcome, nothing else.

No timing, paths or messages are printed, so the same head prints the same
bytes. Exit 0 only when at least one test ran and every test passed or was skipped.
"""
import io
import json
import sys
import unittest
from pathlib import Path


class Collect(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.outcomes = {}

    def _set(self, test, outcome):
        self.outcomes[test.id()] = outcome

    def addSuccess(self, test):
        self._set(test, "PASS")

    def addFailure(self, test, err):
        self._set(test, "FAIL")

    def addError(self, test, err):
        self._set(test, "ERROR")

    def addSkip(self, test, reason):
        self._set(test, "SKIP")

    def addExpectedFailure(self, test, err):
        self._set(test, "EXPECTED_FAILURE")

    def addUnexpectedSuccess(self, test):
        self._set(test, "UNEXPECTED_SUCCESS")

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self._set(test, "FAIL" if issubclass(err[0], test.failureException) else "ERROR")


def main():
    target = Path(sys.argv[1])
    loader = unittest.TestLoader()
    sys.path.insert(0, str(target.parent.resolve()))
    suite = loader.discover(str(target.parent), pattern=target.name, top_level_dir=str(target.parent))
    result = Collect()
    captured = io.StringIO()
    stdout, stderr = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = captured
    try:
        suite.run(result)
    finally:
        sys.stdout, sys.stderr = stdout, stderr
    for test, _ in result.errors:  # import or class-level errors have no addError id of their own
        result.outcomes.setdefault(test.id(), "ERROR")
    passed = bool(result.outcomes) and all(v in ("PASS", "SKIP", "EXPECTED_FAILURE") for v in result.outcomes.values())
    print(json.dumps({"target": str(target), "outcomes": dict(sorted(result.outcomes.items())),
                      "tests": len(result.outcomes), "passed": passed}, sort_keys=True, separators=(",", ":")))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
