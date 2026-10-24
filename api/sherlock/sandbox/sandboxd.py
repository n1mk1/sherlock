"""`sherlock-sandboxd` (TRD §3.4, §11): the one process that keeps root, and only to start
sandbox workers as the `sandbox` user.

The entrypoint starts it as root before dropping the API to `app`. It listens on a Unix socket
(`SANDBOXD_SOCKET`, mode 0660, group `app`) for one JSON line per connection:
`{workdir, request, timeout_s}`. It checks that `workdir` is a direct child of the sandbox root,
hands the directory to `sandbox`, runs `python -I -m sherlock.sandbox.worker` as `sandbox` (under
`unshare -n` when the container allows it) with a minimal environment, kills it on timeout, gives
the directory back to the caller (SO_PEERCRED), and answers `{stdout, stderr, returncode, timed_out}`.
It accepts nothing else.

    python -m sherlock.sandbox.sandboxd      # as root, Linux only
"""

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

SANDBOX_USER = "sandbox"
CLIENT_GROUP = "app"
MAX_REQUEST_BYTES = 4 * 1024 * 1024


def worker_env() -> dict:
    """The worker's whole environment: no secrets from the API process (no LLM_API_KEY)."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "",
    }
    for name in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):  # Windows needs these to start Python
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def _recv_line(conn: socket.socket) -> bytes:
    data = b""
    while not data.endswith(b"\n"):
        chunk = conn.recv(65536)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError("request too large")
    return data


def request(socket_path: str, worker_request: dict, workdir: Path, timeout_s: float) -> tuple[str, str, int, bool]:
    """Client side, used by the API (as `app`)."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout_s + 30)
        conn.connect(socket_path)
        payload = {"workdir": str(workdir), "request": worker_request, "timeout_s": timeout_s}
        conn.sendall(json.dumps(payload).encode() + b"\n")
        answer = json.loads(_recv_line(conn) or b"{}")
    return answer.get("stdout", ""), answer.get("stderr", ""), int(answer.get("returncode", -1)), bool(answer.get("timed_out"))


class Daemon:
    def __init__(self, socket_path: str, sandbox_root: Path, run_as: str | None = SANDBOX_USER,
                 python: str = sys.executable, client_group: str | None = CLIENT_GROUP) -> None:
        self.socket_path = socket_path
        self.client_group = client_group
        self.sandbox_root = sandbox_root.resolve()
        self.run_as = run_as
        self.python = python
        self.use_unshare = run_as is not None and _unshare_works()
        if run_as:
            import pwd

            entry = pwd.getpwnam(run_as)
            self.uid, self.gid = entry.pw_uid, entry.pw_gid

    def handle(self, conn: socket.socket) -> None:
        with conn:
            try:
                payload = json.loads(_recv_line(conn))
                workdir = Path(payload["workdir"]).resolve()
                if workdir.parent != self.sandbox_root or not workdir.is_dir():
                    raise ValueError("workdir must be a directory directly under the sandbox root")
                answer = self.run(workdir, payload["request"], float(payload["timeout_s"]), _peer_uid(conn))
            except Exception as exc:  # noqa: BLE001 - the client gets the reason, the daemon keeps running
                answer = {"stdout": "", "stderr": f"sandboxd: {exc}", "returncode": -1, "timed_out": False}
            conn.sendall(json.dumps(answer).encode() + b"\n")

    def run(self, workdir: Path, worker_request: dict, timeout_s: float, caller_uid: int | None) -> dict:
        command = [self.python, "-I", "-m", "sherlock.sandbox.worker"]
        preexec = None
        if self.run_as:
            _chown_tree(workdir, self.uid, self.gid)
            if self.use_unshare:
                command = ["unshare", "-n", "--"] + command

            def preexec():  # noqa: F811 - runs in the child before exec
                os.setgroups([])
                os.setgid(self.gid)
                os.setuid(self.uid)
        try:
            proc = subprocess.run(command, input=json.dumps(worker_request), capture_output=True, text=True,
                                  cwd=workdir, timeout=timeout_s, env=worker_env(), preexec_fn=preexec)
            answer = {"stdout": proc.stdout, "stderr": proc.stderr[-4000:], "returncode": proc.returncode, "timed_out": False}
        except subprocess.TimeoutExpired:
            answer = {"stdout": "", "stderr": "", "returncode": -9, "timed_out": True}
        finally:
            if self.run_as and caller_uid is not None:
                _chown_tree(workdir, caller_uid, -1)
        return answer

    def serve_forever(self) -> None:
        path = Path(self.socket_path)
        path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.socket_path)
        if self.client_group:
            import grp

            os.chown(self.socket_path, 0, grp.getgrnam(self.client_group).gr_gid)
        os.chmod(self.socket_path, 0o660)
        server.listen(16)
        while True:
            conn, _ = server.accept()
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()


def _peer_uid(conn: socket.socket) -> int | None:
    try:
        import struct

        creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        return struct.unpack("3i", creds)[1]
    except (AttributeError, OSError):
        return None


def _chown_tree(root: Path, uid: int, gid: int) -> None:
    os.chown(root, uid, gid)
    for path in root.rglob("*"):
        os.chown(path, uid, gid)


def _unshare_works() -> bool:
    try:
        return subprocess.run(["unshare", "-n", "true"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main() -> int:
    from sherlock.config import get_settings
    from sherlock.sandbox.runner import sandbox_root

    settings = get_settings()
    if not settings.sandboxd_socket:
        print("sandboxd: SANDBOXD_SOCKET is not set", file=sys.stderr)
        return 2
    root = sandbox_root(settings)
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o1777)  # like /tmp: anyone may create, only owners may delete
    daemon = Daemon(settings.sandboxd_socket, root)
    print(f"sandboxd: listening on {settings.sandboxd_socket}; network namespace: {daemon.use_unshare}", file=sys.stderr)
    daemon.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
