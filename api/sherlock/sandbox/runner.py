"""Parent side of the sandbox (TRD §3.4): static check, a fresh temp directory outside `/data`,
one worker per run (through `sherlock-sandboxd` when it's configured, else a direct subprocess),
a wall-clock timeout, the output copied back, and a `sandbox_runs` row for every execution.
"""

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sherlock.config import Settings
from sherlock.db.util import now_iso
from sherlock.sandbox import sandboxd
from sherlock.sandbox.static_check import check

WALL_FACTOR = 2      # wall-clock timeout = CPU limit × 2 (+5 s for start-up)
STARTUP_S = 5


@dataclass
class SandboxResult:
    ok: bool
    error: str | None = None
    rows_in: int | None = None
    rows_out: int | None = None
    columns_added: list[str] = field(default_factory=list)
    columns_removed: list[str] = field(default_factory=list)
    traceback_tail: str | None = None
    stdout_tail: str | None = None
    violations: list[str] = field(default_factory=list)
    wall_ms: int = 0
    timed_out: bool = False


def sandbox_root(settings: Settings) -> Path:
    return Path(settings.sandbox_tmp) if settings.sandbox_tmp else Path(tempfile.gettempdir()) / "sherlock-sandbox"


def worker_command() -> list[str]:
    return [sys.executable, "-I", "-m", "sherlock.sandbox.worker"]


def _direct(request: dict, workdir: Path, timeout_s: float) -> tuple[str, str, int, bool]:
    try:
        proc = subprocess.run(
            worker_command(), input=json.dumps(request), capture_output=True, text=True,
            cwd=workdir, timeout=timeout_s, env=sandboxd.worker_env(),
        )
        return proc.stdout, proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired as exc:
        return exc.stdout or "", exc.stderr or "", -9, True


def execute(
    settings: Settings,
    code: str,
    input_parquet: Path,
    output_parquet: Path,
    *,
    db: sqlite3.Connection | None = None,
    dataset_id: str | None = None,
    job_id: str | None = None,
    skip_static_check: bool = False,
) -> SandboxResult:
    """Run `code` on the version at `input_parquet`; on success the result is at `output_parquet`.
    `skip_static_check` exists only for tests of the worker's own defences."""
    started = time.monotonic()
    violations = [] if skip_static_check else [str(v) for v in check(code)]
    if violations:
        result = SandboxResult(ok=False, error="The code uses something the sandbox doesn't allow.", violations=violations)
        _log(db, dataset_id, job_id, code, result)
        return result

    workdir = sandbox_root(settings) / uuid.uuid4().hex
    workdir.mkdir(parents=True)
    try:
        shutil.copyfile(input_parquet, workdir / "input.parquet")
        request = {
            "input": str(workdir / "input.parquet"),
            "output": str(workdir / "output.parquet"),
            "code": code,
            "cpu_s": settings.sandbox_cpu_s,
            "mem_mb": settings.sandbox_mem_mb,
        }
        timeout_s = settings.sandbox_cpu_s * WALL_FACTOR + STARTUP_S
        if settings.sandboxd_socket:
            stdout, stderr, code_rc, timed_out = sandboxd.request(settings.sandboxd_socket, request, workdir, timeout_s)
        else:
            stdout, stderr, code_rc, timed_out = _direct(request, workdir, timeout_s)
        result = _parse(stdout, stderr, code_rc, timed_out)
        if result.ok:
            output_parquet.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(workdir / "output.parquet", output_parquet)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    result.wall_ms = int((time.monotonic() - started) * 1000)
    _log(db, dataset_id, job_id, code, result)
    return result


def _parse(stdout: str, stderr: str, returncode: int, timed_out: bool) -> SandboxResult:
    if timed_out:
        return SandboxResult(ok=False, error="The step took too long and was stopped.", timed_out=True)
    lines = [line for line in (stdout or "").splitlines() if line.strip()]
    if not lines:
        tail = (stderr or "").strip().splitlines()[-1:] or [f"exit code {returncode}"]
        killed = returncode in (-9, 137, -24, 152)  # SIGKILL / SIGXCPU: a resource limit hit
        reason = "The step hit the sandbox's CPU or memory limit." if killed else f"The sandbox worker failed: {tail[0]}"
        return SandboxResult(ok=False, error=reason)
    data = json.loads(lines[-1])
    return SandboxResult(
        ok=bool(data.get("ok")), error=data.get("error"), rows_in=data.get("rows_in"), rows_out=data.get("rows_out"),
        columns_added=data.get("columns_added") or [], columns_removed=data.get("columns_removed") or [],
        traceback_tail=data.get("traceback_tail"), stdout_tail=data.get("stdout_tail"),
    )


def _log(db, dataset_id, job_id, code, result: SandboxResult) -> None:
    if db is None:
        return
    db.execute(
        "INSERT INTO sandbox_runs (dataset_id, job_id, step_id, code_hash, rows_in, rows_out, cpu_ms, wall_ms, ok, error, created_at) "
        "VALUES (?, ?, NULL, ?, ?, ?, NULL, ?, ?, ?, ?)",
        (dataset_id, job_id, hashlib.sha256(code.encode()).hexdigest(), result.rows_in, result.rows_out,
         result.wall_ms, int(result.ok), result.error, now_iso()),
    )
