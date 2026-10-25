"""Prompts for the Cleaner's three calls (TRD §7.2, §8.3): diagnose, propose and critic.

Each is a system message (rules) and a user message whose data sits inside `<data>` blocks.
Templates are plain text files next to this module, filled with `str.format`.
"""

from pathlib import Path

HERE = Path(__file__).parent


def load(name: str) -> str:
    return (HERE / f"{name}.txt").read_text(encoding="utf-8")


SYSTEM = load("system")
DIAGNOSE = load("diagnose")
PROPOSE = load("propose")
CRITIC = load("critic")
HELPERS = load("helpers")
