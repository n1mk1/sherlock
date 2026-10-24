#!/bin/sh
# Starts as root, prepares /data, then drops the API to the `app` user (TRD §11).
# `sherlock-sandboxd` (the only process that keeps root) is started here once the
# sandbox lands (Implementation Plan D2.4).
set -eu

DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"
# A mounted shared filesystem may not allow chown; the storage check in /healthz reports it.
chown app:app "$DATA_DIR" 2>/dev/null || echo "entrypoint: could not chown $DATA_DIR" >&2

exec setpriv --reuid=app --regid=app --init-groups --inh-caps=-all -- "$@"
