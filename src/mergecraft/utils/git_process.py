"""Bounded subprocess capture for Git commands, with process-group cleanup.

Exports:
    run_git_process: Capture a bounded amount of output from a hardened argv.
"""

from __future__ import annotations

import os
import selectors
import subprocess
import time

from mergecraft.utils.process_group import kill_process_group, track_process_group
from mergecraft.utils.process_scope import check_process_cancelled


def run_git_process(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    output_limit: int,
    timeout: float,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Capture at most ``output_limit`` combined bytes, refusing partial results.

    Both pipes are drained incrementally to avoid deadlock or unbounded capture.
    Timeouts, cancellation and output overflow terminate the entire process group.
    """
    check_process_cancelled()
    with (
        subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as process,
        track_process_group(process),
    ):
        stdout = bytearray()
        stderr = bytearray()
        deadline = time.monotonic() + timeout
        try:
            if input_text is not None:
                assert process.stdin is not None
                process.stdin.write(input_text.encode())
                process.stdin.close()
            with selectors.DefaultSelector() as selector:
                assert process.stdout is not None
                assert process.stderr is not None
                selector.register(process.stdout, selectors.EVENT_READ, stdout)
                selector.register(process.stderr, selectors.EVENT_READ, stderr)
                while selector.get_map():
                    check_process_cancelled()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(argv, timeout)
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if len(stdout) + len(stderr) + len(chunk) > output_limit:
                            raise RuntimeError(
                                f"git output exceeded {output_limit} bytes; partial output refused"
                            )
                        key.data.extend(chunk)
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
            check_process_cancelled()
        except BaseException:
            kill_process_group(process.pid)
            process.wait(timeout=5)
            raise
        return subprocess.CompletedProcess(
            argv,
            process.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
