"""Write the API's OpenAPI schema to web/src/api/openapi.json, the input of `pnpm openapi`.

Run from the repo root:  uv run --project api python scripts/dump_openapi.py
"""

import json
import os
from pathlib import Path

# The app refuses to start without NVIDIA roles; the schema doesn't depend on their values.
for key, value in {"MODEL_LARGE": "nvidia/nemotron-x-ultra", "MODEL_MEDIUM": "nvidia/nemotron-x-super",
                   "MODEL_SMALL": "nvidia/nemotron-x-nano"}.items():
    os.environ.setdefault(key, value)

from sherlock.main import create_app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "web" / "src" / "api" / "openapi.json"

if __name__ == "__main__":
    schema = create_app().openapi()
    OUT.write_bytes((json.dumps(schema, indent=1, sort_keys=True) + "\n").encode("utf-8"))  # LF on Windows too
    print(f"wrote {OUT} ({len(schema['paths'])} paths)")
