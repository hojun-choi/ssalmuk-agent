import subprocess
import unittest
from unittest import mock

from internal.tools.shell import run_cli


class RunCliTest(unittest.TestCase):
    def test_windows_wraps_cmd_exe_c(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["cmd.exe", "/c", "codex", "--help"],
            returncode=0,
            stdout=b"ok",
            stderr=b"",
        )
        with mock.patch("internal.tools.shell.platform.system", return_value="Windows"):
            with mock.patch("internal.tools.shell.subprocess.run", return_value=completed) as run_mock:
                rc, stdout, stderr = run_cli(["codex", "--help"], timeout_sec=7)

        self.assertEqual(rc, 0)
        self.assertEqual(stdout, "ok")
        self.assertEqual(stderr, "")
        run_mock.assert_called_once()
        called_cmd = run_mock.call_args.args[0]
        self.assertEqual(called_cmd, ["cmd.exe", "/c", "codex", "--help"])
        self.assertEqual(run_mock.call_args.kwargs["shell"], False)
        self.assertEqual(run_mock.call_args.kwargs["text"], False)

    def test_utf8_decode_replace_does_not_crash(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["gemini", "--help"],
            returncode=0,
            stdout=b"\xed\x95\x9c\xea\xb8\x80\xff",
            stderr=b"\xfferr",
        )
        with mock.patch("internal.tools.shell.platform.system", return_value="Linux"):
            with mock.patch("internal.tools.shell.subprocess.run", return_value=completed):
                rc, stdout, stderr = run_cli(["gemini", "--help"])

        self.assertEqual(rc, 0)
        self.assertIn("한글", stdout)
        self.assertIn("\ufffd", stdout)
        self.assertTrue(stderr.startswith("\ufffd"))


if __name__ == "__main__":
    unittest.main()
