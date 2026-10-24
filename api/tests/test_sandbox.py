"""Sandbox protocol tests (Implementation Plan D2.4): happy path, timeout, memory, forbidden
imports, the worker's own defences, and sherlock-sandboxd. POSIX-only cases skip on Windows; the
root-only case runs where tests run as root (the Docker check in the README)."""

import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import duckdb
import pytest

from sherlock.config import Settings, get_settings
from sherlock.db.connection import connect
from sherlock.db.migrate import migrate
from sherlock.sandbox import sandboxd
from sherlock.sandbox.runner import execute, sandbox_root
from sherlock.sandbox.static_check import check

POSIX = os.name != "nt"


@pytest.fixture
def version(tmp_path) -> Path:
    path = tmp_path / "v1.parquet"
    duckdb.connect().execute(
        "COPY (SELECT i::BIGINT AS _row_id, NULL::VARCHAR AS _quarantine_reason, "
        "CASE WHEN i % 4 = 0 THEN NULL ELSE (20 + i % 30)::VARCHAR END AS age, 'x' || i AS name "
        f"FROM range(1, 201) t(i)) TO '{path.as_posix()}' (FORMAT PARQUET)")
    return path


def settings(**overrides) -> Settings:
    base = get_settings().model_dump()
    base.update({"sandbox_cpu_s": 5, "sandbox_mem_mb": 1024, "sandboxd_socket": ""}, **overrides)
    return Settings(_env_file=None, **base)


def read(path: Path, sql: str):
    return duckdb.connect().execute(sql.replace("{p}", f"read_parquet('{path.as_posix()}')")).fetchall()


# --- static check ---------------------------------------------------------------------


def test_allowed_code_passes():
    code = (
        "import re\nimport numpy as np\nfrom datetime import datetime\n"
        "titles = df['name'].str.extract(r'(\\w+)')\n"
        "result = df.assign(age=pd.to_numeric(df['age'], errors='coerce').fillna(30))\n"
    )
    assert check(code) == []


@pytest.mark.parametrize("code", [
    "import os", "import subprocess", "from os import path", "import socket", "import requests",
    "import urllib.request", "import importlib", "from . import x",
    "__import__('os')", "eval('1')", "exec('x=1')", "open('/data/x')", "compile('1', 'f', 'eval')",
    "getattr(df, 'x')", "globals()", "breakpoint()",
    "df.__class__", "x = ().__class__.__bases__", "__builtins__",
    "pd.read_csv('x')", "df.to_csv('x')", "df.to_parquet('x')", "df.to_pickle('x')",
    "np.load('x')", "np.fromfile('x')", "pd.io.common.os.system('ls')", "np.lib.npyio",
    "global df", "result = df[",
])
def test_forbidden_code_is_rejected(code):
    assert check(code), code


def test_to_datetime_and_friends_are_allowed():
    assert check("result = df.assign(d=pd.to_datetime(df['age']), n=pd.to_numeric(df['age']))") == []


# --- execution ------------------------------------------------------------------------


def test_happy_path_and_log(version, tmp_path):
    db = connect(get_settings())
    migrate(db)
    out = tmp_path / "out.parquet"
    result = execute(settings(), "result = df.assign(age=df['age'].fillna('30'), flag=1)", version, out,
                     db=db, dataset_id="ds_x")
    assert result.ok, result.error
    assert (result.rows_in, result.rows_out, result.columns_added) == (200, 200, ["flag"])
    assert read(out, "SELECT count(*) - count(age) FROM {p}") == [(0,)]
    row = db.execute("SELECT * FROM sandbox_runs").fetchone()
    assert (row["dataset_id"], row["ok"], row["rows_in"]) == ("ds_x", 1, 200)
    assert len(row["code_hash"]) == 64
    assert not any(sandbox_root(settings()).glob("*"))  # temp dirs removed
    db.close()


def test_forbidden_import_never_starts_a_worker(version, tmp_path):
    started = time.monotonic()
    result = execute(settings(), "import os\nresult = df", version, tmp_path / "out.parquet")
    assert not result.ok and result.violations == ["line 1: import of 'os' is not allowed"]
    assert time.monotonic() - started < 0.5
    assert not (tmp_path / "out.parquet").exists()


@pytest.mark.parametrize("code,error", [
    ("__import__('os')", "not allowed"),
    ("import os", "not allowed"),
    ("open('x')", "NameError"),
    ("eval('1')", "NameError"),
    ("result = pd.read_csv('http://127.0.0.1:9/x.csv')", ""),
])
def test_worker_defences_hold_without_the_static_check(version, tmp_path, code, error):
    result = execute(settings(), code, version, tmp_path / "out.parquet", skip_static_check=True)
    assert not result.ok
    assert error in (result.error or "")


def test_errors_are_reported_with_a_traceback(version, tmp_path):
    result = execute(settings(), "result = df['missing_column']", version, tmp_path / "out.parquet")
    assert not result.ok and result.error.startswith("KeyError")
    assert "missing_column" in result.traceback_tail


def test_code_must_leave_a_dataframe(version, tmp_path):
    result = execute(settings(), "x = 1", version, tmp_path / "out.parquet")
    assert not result.ok and "result" in result.error


def test_timeout(version, tmp_path):
    started = time.monotonic()
    result = execute(settings(sandbox_cpu_s=1), "while True:\n    pass", version, tmp_path / "out.parquet")
    assert not result.ok
    assert result.timed_out or "limit" in result.error
    assert time.monotonic() - started < 15


@pytest.mark.skipif(not POSIX, reason="RLIMIT_AS needs POSIX")
def test_memory_limit(version, tmp_path):
    code = "big = np.ones(10**9)\nresult = df"
    result = execute(settings(sandbox_mem_mb=600), code, version, tmp_path / "out.parquet")
    assert not result.ok
    assert "MemoryError" in (result.error or "") or "limit" in (result.error or "")


def test_worker_env_has_no_secrets(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "secret-value")
    env = sandboxd.worker_env()
    assert "LLM_API_KEY" not in env and "secret-value" not in env.values()
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:9"


# --- sherlock-sandboxd ----------------------------------------------------------------


def _start_daemon(sock_path: str, root: Path, run_as):
    daemon = sandboxd.Daemon(sock_path, root, run_as=run_as, client_group=None)
    threading.Thread(target=daemon.serve_forever, daemon=True).start()
    for _ in range(100):
        if os.path.exists(sock_path):
            return daemon
        time.sleep(0.02)
    raise RuntimeError("daemon did not start")


@pytest.mark.skipif(not POSIX, reason="Unix sockets and setuid are POSIX")
def test_daemon_protocol(version, tmp_path):
    root = Path(tempfile.mkdtemp())
    sock = str(Path(tempfile.mkdtemp()) / "sbx.sock")
    _start_daemon(sock, root, run_as=None)
    result = execute(settings(sandboxd_socket=sock, sandbox_tmp=str(root)), "result = df.head(5)", version,
                     tmp_path / "out.parquet")
    assert result.ok, result.error
    assert result.rows_out == 5

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:  # a workdir outside the root is refused
        conn.connect(sock)
        conn.sendall(b'{"workdir": "/etc", "request": {}, "timeout_s": 5}\n')
        assert b"workdir must be" in conn.recv(65536)


@pytest.mark.skipif(not POSIX or os.geteuid() != 0, reason="needs root to switch to the sandbox user")
def test_worker_runs_as_sandbox_user_and_cannot_read_protected_files(version, tmp_path):
    import pwd

    try:
        pwd.getpwnam("sandbox")
    except KeyError:
        pytest.skip("no sandbox user")
    secret_dir = Path(tempfile.mkdtemp())
    os.chmod(secret_dir, 0o700)
    (secret_dir / "secret.csv").write_text("a\n1\n")
    root = Path(tempfile.mkdtemp())
    os.chmod(root, 0o1777)
    sock = str(Path(tempfile.mkdtemp()) / "sbx.sock")
    _start_daemon(sock, root, run_as="sandbox")
    s = settings(sandboxd_socket=sock, sandbox_tmp=str(root))
    ok = execute(s, "result = df.head(3)", version, tmp_path / "out.parquet")
    assert ok.ok, ok.error
    denied = execute(s, f"result = pd.read_csv('{secret_dir}/secret.csv')", version, tmp_path / "out2.parquet",
                     skip_static_check=True)
    assert not denied.ok and "Permission" in denied.error
