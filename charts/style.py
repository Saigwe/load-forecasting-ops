"""Shared chart style for README charts: one palette, thin marks, direct labels, recessive grid.

Categorical colours are used in fixed order and follow the entity, never its rank.
Status colours are reserved for good / warning / critical states.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402,F401

S = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]          # categorical slots, fixed order
SEQ = ["#cde2fb", "#86b6ef", "#2a78d6", "#0d366b"]        # sequential, light to dark
GOOD, WARNING, SERIOUS, CRITICAL = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
MUTED, TEXT, TEXT2, GRID, AXIS, SURFACE = "#898781", "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"], "font.size": 9.5,
    "axes.edgecolor": AXIS, "axes.labelcolor": TEXT2, "axes.titlesize": 11.5, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.titlepad": 22, "axes.titlecolor": TEXT,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": TEXT2, "ytick.labelcolor": TEXT2,
    "xtick.major.size": 0, "ytick.major.size": 0, "lines.linewidth": 2, "legend.frameon": False,
    "legend.fontsize": 9, "axes.axisbelow": True,
})


def fig(w: float = 8, h: float = 3.6):
    return plt.subplots(figsize=(w, h), dpi=150)


def head(ax, title: str, sub: str | None = None, legend: bool = False, ncol: int = 4, flush: bool = False) -> None:
    """Stack title, subtitle and legend above the plot so they never overlap.

    flush=True starts the title and subtitle at the figure's left edge (for charts with long y labels)."""
    off = 4
    if legend:
        n = len(ax.get_legend_handles_labels()[0])
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=ncol, borderaxespad=0.25, handlelength=1.4,
                  columnspacing=1.4)
        off += 18 * -(-n // ncol)
    xy, xyc = ((0.012, 1), ("figure fraction", "axes fraction")) if flush else ((0, 1), "axes fraction")
    if sub:
        ax.annotate(sub, xy, xycoords=xyc, xytext=(0, off), textcoords="offset points", color=TEXT2, fontsize=9,
                    va="bottom", annotation_clip=False)
        off += 15
    if flush:
        ax.annotate(title, xy, xycoords=xyc, xytext=(0, off + 2), textcoords="offset points", color=TEXT,
                    fontsize=11.5, fontweight="bold", va="bottom", annotation_clip=False)
        ax.set_title(" ", pad=off + 2)   # reserves the space in tight_layout
    else:
        ax.set_title(title, pad=off + 2)


def fmt(ax, axis: str = "y", kind: str = "num", d: int = 0) -> None:
    f = {"pct": lambda v, _: f"{v * 100:.{d}f}%", "usd": lambda v, _: f"${v:,.{d}f}",
         "gbp": lambda v, _: f"£{v:,.{d}f}", "num": lambda v, _: f"{v:,.{d}f}",
         "k": lambda v, _: f"{v / 1e3:,.{d}f}k", "m": lambda v, _: f"{v / 1e6:,.{d}f}M",
         "bn": lambda v, _: f"{v / 1e9:,.{d}f}bn"}[kind]
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(FuncFormatter(f))


def hbar(ax, labels, values, colors=None, label_fmt=lambda v: f"{v:,.0f}", height: float = 0.62) -> None:
    """Horizontal bars, largest first if the caller sorts, value labels at the bar end."""
    colors = colors or [S[0]] * len(values)
    y = range(len(values))
    ax.barh(list(y), values, color=colors, height=height)
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.spines["left"].set_visible(False)
    hi = max(values) if len(values) else 1
    for i, v in enumerate(values):
        ax.text(v + hi * 0.01, i, label_fmt(v), va="center", fontsize=8.5, color=TEXT2)
    ax.set_xlim(0, hi * 1.15)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}" if hi >= 10 else f"{v:.1f}"))


def vbar_labels(ax, bars, label_fmt=lambda v: f"{v:,.0f}") -> None:
    for b in bars:
        h = b.get_height()
        ax.text(b.get_x() + b.get_width() / 2, h, label_fmt(h), ha="center", va="bottom", fontsize=8.5, color=TEXT2)


def end_label(ax, x, y, text: str, color: str = TEXT2) -> None:
    ax.annotate(text, (x, y), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8.5, color=color)


def save(f, path, note: str | None = None) -> Path:
    if note:
        f.text(0.01, 0.01, note, color=MUTED, fontsize=7.5)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f.tight_layout()
    f.savefig(path, dpi=150)
    plt.close(f)
    return path
