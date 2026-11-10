"""The suite's own safety nets, in support.py."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from support import CODE_ROOT  # Points Pyrite at a throwaway workspace before it loads.

HANGS = '''
import time
import unittest

import support  # noqa: F401


class Hangs(unittest.TestCase):
    def test_waits_forever(self):
        time.sleep(60)


unittest.main()
'''


class TestTimeLimit(unittest.TestCase):
    def test_a_hung_test_prints_its_stack_and_fails_the_run(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            script = Path(tmp) / "hangs.py"
            script.write_text(HANGS, encoding="utf-8")
            env = {**os.environ, "PYRITE_TEST_LIMIT": "2", "PYTHONPATH": str(CODE_ROOT / "tools" / "tests")}
            started = time.monotonic()
            ran = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=50)
        self.assertLess(time.monotonic() - started, 50)
        self.assertNotEqual(ran.returncode, 0)
        self.assertIn("Timeout", ran.stderr)
        self.assertIn("test_waits_forever", ran.stderr)  # The stack names the test that hung.

    @unittest.skipIf(os.environ.get("PYRITE_TEST_LIMIT"), "PYRITE_TEST_LIMIT sets another limit for this run.")
    def test_the_limit_is_far_under_the_ci_job_limit(self):
        import support

        self.assertGreater(support.TEST_LIMIT_SECONDS, 60)
        self.assertLessEqual(support.TEST_LIMIT_SECONDS, 10 * 60)


if __name__ == "__main__":
    unittest.main()
