"""A throwaway API for the end-to-end test (`web/playwright.config.ts`): it empties its data folder,
then serves the API and the built web app on one port, like production."""

import argparse
import os
import shutil

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8010)
    port = parser.parse_args().port
    data = os.environ.get("DATA_DIR", "")
    if "sherlock-e2e" not in data:
        raise SystemExit("refusing to empty a DATA_DIR that isn't the end-to-end test's")
    shutil.rmtree(data, ignore_errors=True)
    uvicorn.run("sherlock.main:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
