#!/bin/sh
# Starts as root, prepares /data, starts sherlock-sandboxd (the only process that keeps root,
# and only to start sandbox workers as the `sandbox` user), then drops the API to `app` (TRD §11).
set -eu

DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"
# A mounted filesystem may not allow chown; the storage check in /healthz reports it.
chown app:app "$DATA_DIR" 2>/dev/null || echo "entrypoint: could not chown $DATA_DIR" >&2
# Only `app` may enter /data: sandbox workers (user `sandbox`) can't read any dataset.
chmod 700 "$DATA_DIR" 2>/dev/null || echo "entrypoint: could not chmod $DATA_DIR" >&2

if [ -n "${SANDBOXD_SOCKET:-}" ]; then
    mkdir -p "$(dirname "$SANDBOXD_SOCKET")"
    /opt/venv/bin/python -m sherlock.sandbox.sandboxd &
    for _ in $(seq 1 50); do
        [ -S "$SANDBOXD_SOCKET" ] && break
        sleep 0.1
    done
    [ -S "$SANDBOXD_SOCKET" ] || echo "entrypoint: sandboxd did not start" >&2
fi

exec setpriv --reuid=app --regid=app --init-groups --inh-caps=-all -- "$@"
