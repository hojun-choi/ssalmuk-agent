from __future__ import annotations

import platform
import subprocess
from typing import Mapping


def run_cli(
    cmd_list: list[str],
    cwd: str | None = None,
    timeout_sec: int = 60,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    run_cmd = ["cmd.exe", "/c", *cmd_list] if platform.system() == "Windows" else list(cmd_list)
    proc = subprocess.run(
        run_cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=False,
        shell=False,
        timeout=max(1, timeout_sec),
    )
    stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    return proc.returncode, stdout, stderr
