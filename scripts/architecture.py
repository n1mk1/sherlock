"""Draw `docs/architecture.png` (Implementation Plan §7): the request and data flow, as the README's
Mermaid diagram shows it, as an image for places that don't render Mermaid (Devpost).

    uv run --project api python scripts/architecture.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "architecture.png"
INK, MUTED, ACCENT, NVIDIA, CARD, BG = "#2e3035", "#64666b", "#2f6b62", "#76b900", "#f7f6f3", "#eeece8"


def box(ax, x, y, w, h, title, lines, edge=INK, fill=CARD, title_color=INK):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", linewidth=1.6,
                                edgecolor=edge, facecolor=fill))
    ax.text(x + 0.18, y + h - 0.32, title, fontsize=12.5, fontweight="bold", color=title_color, va="top")
    for i, line in enumerate(lines):
        ax.text(x + 0.18, y + h - 0.78 - i * 0.36, line, fontsize=9.6, color=MUTED, va="top")


def arrow(ax, a, b, label="", color=INK, rad=0.0, label_at=0.5, dy=0.16):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=14, linewidth=1.5, color=color,
                                 connectionstyle=f"arc3,rad={rad}"))
    if label:
        mx, my = a[0] + (b[0] - a[0]) * label_at, a[1] + (b[1] - a[1]) * label_at
        ax.text(mx, my + dy, label, fontsize=9, color=color, ha="center", va="bottom",
                bbox={"boxstyle": "round,pad=0.25", "facecolor": BG, "edgecolor": "none"})


def main() -> None:
    fig, ax = plt.subplots(figsize=(14, 7.6), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7.6)
    ax.axis("off")
    ax.text(0.3, 7.3, "Sherlock: how a CSV becomes defensible answers", fontsize=16, fontweight="bold", color=INK, va="top")
    ax.text(0.3, 6.85, "Every number comes from executed code; the model writes words around chips and plans the code.",
            fontsize=10.5, color=MUTED, va="top")

    box(ax, 0.3, 3.5, 3.3, 2.7, "Browser", ["React 18 · Vite", "Dashboard: Bklit + visx charts", "CSV: Glide Data Grid",
                                              "Flow: React Flow canvas", "Chat bar · story cards"])
    box(ax, 4.6, 2.2, 4.6, 4.0, "Sherlock API (FastAPI, Render)", ["Job runner: clean · build · stories · ML",
        "Chat agent: route → answer → compose → verify", "Cleaner: diagnose → propose → verify → gate",
        "Storyteller: fact sheets → narrate → check", "Cascade: a change re-tells only its stories",
        "Notebook exporter", "Rate limits · budgets · cookie identity"], edge=ACCENT, title_color=ACCENT)
    box(ax, 10.2, 4.3, 3.5, 1.9, "Nebius Token Factory", ["Nemotron 3 Ultra: the Cleaner",
        "Nemotron 3 Super: stories, SQL", "Nemotron 3 Nano: routing"], edge=NVIDIA, title_color="#4a7a00")
    box(ax, 10.2, 1.9, 3.5, 1.9, "Persistent disk /data", ["SQLite (WAL): app state, steps,", "cards, runs, events",
                                                          "Parquet: one file per version"])
    box(ax, 4.6, 0.3, 2.2, 1.45, "DuckDB", ["in memory,", "one per version"])
    box(ax, 7.0, 0.3, 2.2, 1.45, "Sandbox", ["pandas fixes,", "no network"])
    box(ax, 0.3, 0.3, 3.3, 1.9, "Jupyter notebook", ["rebuilds every step, widget,", "model and story card",
                                                     "from the raw CSV"])

    arrow(ax, (3.6, 5.2), (4.6, 5.2), "REST", ACCENT)
    arrow(ax, (4.6, 4.3), (3.6, 4.3), "SSE events", ACCENT)
    arrow(ax, (9.2, 5.0), (10.2, 5.0), "OpenAI API", INK, dy=0.1)
    arrow(ax, (9.2, 3.0), (10.2, 3.0), "versions, state", INK)
    arrow(ax, (5.7, 2.2), (5.7, 1.75), "", INK)
    arrow(ax, (8.1, 2.2), (8.1, 1.75), "", INK)
    arrow(ax, (4.6, 2.6), (3.6, 1.6), "export", ACCENT, dy=0.05)

    fig.savefig(OUT, facecolor=BG, bbox_inches="tight")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
