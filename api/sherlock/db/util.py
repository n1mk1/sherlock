"""IDs and timestamps (Schema §1): prefixed ULIDs and ISO-8601 UTC strings."""

import os
import time
from datetime import UTC, datetime

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """A 26-character ULID: 48-bit millisecond timestamp + 80 random bits, Crockford base32."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    """`usr_01J…`, `ds_01J…`: a 2–4 letter prefix and a ULID, so IDs sort by creation time."""
    return f"{prefix}_{ulid()}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
