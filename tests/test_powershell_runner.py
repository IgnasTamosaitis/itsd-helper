import os
import subprocess
import unittest
from unittest.mock import patch

from ad_automation import run_ps


class PowerShellRunnerTests(unittest.TestCase):
    @patch("ad_automation.subprocess.run")
    def test_large_script_is_executed_from_a_temporary_file(self, mock_run):
        large_script = "Write-Output 'group'\n" * 2_000
        captured = {}

        def inspect_invocation(command, **kwargs):
            script_path = command[-1]
            captured["command"] = command
            captured["path"] = script_path
            self.assertTrue(os.path.isfile(script_path))
            with open(script_path, encoding="utf-8-sig") as script_file:
                captured["script"] = script_file.read()
            return subprocess.CompletedProcess(command, 0, " done \n", "")

        mock_run.side_effect = inspect_invocation

        stdout, stderr, code = run_ps(large_script)

        self.assertEqual((stdout, stderr, code), ("done", "", 0))
        self.assertEqual(captured["command"][-2], "-File")
        self.assertNotIn(large_script, captured["command"])
        self.assertIn(large_script, captured["script"])
        self.assertFalse(os.path.exists(captured["path"]))

    @patch("ad_automation.subprocess.run")
    def test_temporary_script_is_removed_when_powershell_fails(self, mock_run):
        captured = {}

        def fail_invocation(command, **kwargs):
            captured["path"] = command[-1]
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        mock_run.side_effect = fail_invocation

        with self.assertRaises(subprocess.TimeoutExpired):
            run_ps("Start-Sleep -Seconds 10", timeout=1)

        self.assertFalse(os.path.exists(captured["path"]))


if __name__ == "__main__":
    unittest.main()
