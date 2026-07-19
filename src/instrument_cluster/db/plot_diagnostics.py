#!/usr/bin/env python3
"""Diagnostics for the track-identification database (tracks.json).

Two figures:

  overview      every track's bounding box (recessive gray) and start/finish
                gate (dark marks) — shows how heavily the boxes overlap and
                how well-separated the gates are.
  brands hatch  zoom on the Brands Hatch GP vs Indy pair: shared gate, same
                crossing direction, nested bounding boxes — the shape of
                every "gate-sharing siblings" ambiguity.

Also prints, for the terminal, the Brands Hatch numbers and every group of
tracks whose gates coincide (the cases a gate crossing alone cannot
separate — see ../signals/track_signal.py for how they are resolved).

Usage:
  python plot_diagnostics.py                 write overview.png + brands_hatch.png
  python plot_diagnostics.py --interactive   open zoomable windows with hover
                                             tooltips (scroll = zoom at cursor,
                                             hover = track names, r = reset view)

See README.md in this directory for the full guide.
"""

import argparse
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "tracks.json"

# Gates whose midpoints lie within this radius are reported as one
# gate-sharing group (forward/reverse pairs, nested sub-layouts, ...).
GATE_GROUP_RADIUS_M = 25.0

# Hover hit-test slack, in screen points (how close the cursor must be to a
# line before its track is listed in the tooltip).
PICK_RADIUS_BOX_PT = 3
PICK_RADIUS_GATE_PT = 6

# Cap the tooltip: dense spots (e.g. Lago Maggiore's 8-way gate group plus
# the boxes underneath) can hit a lot of tracks at once.
TOOLTIP_MAX_NAMES = 10


def load_data(path: Path = DB_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


def box_xy(b: dict):
    xs = [b["min_x"], b["max_x"], b["max_x"], b["min_x"], b["min_x"]]
    zs = [b["min_z"], b["min_z"], b["max_z"], b["max_z"], b["min_z"]]
    return xs, zs


def area(b: dict) -> float:
    return (b["max_x"] - b["min_x"]) * (b["max_z"] - b["min_z"])


def gate_groups(data: dict, radius: float = GATE_GROUP_RADIUS_M):
    """Groups of track ids whose gate midpoints lie within `radius` metres."""
    mids = {}
    for tid, t in data.items():
        g = t.get("gate")
        if not g:
            continue
        mids[tid] = ((g["p1"]["x"] + g["p2"]["x"]) / 2, (g["p1"]["z"] + g["p2"]["z"]) / 2)

    groups = []
    seen = set()
    for tid, (x, z) in mids.items():
        if tid in seen:
            continue
        grp = [tid]
        seen.add(tid)
        for other, (ox, oz) in mids.items():
            if other not in seen and math.hypot(x - ox, z - oz) < radius:
                grp.append(other)
                seen.add(other)
        if len(grp) > 1:
            groups.append(grp)
    return groups


def _style(ax, title: str) -> None:
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("z (m)")
    ax.set_title(title)
    ax.grid(True, color="#eceff1", lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def build_overview(ax, data: dict):
    """Draw all bounds + gates; return (artist, label, kind) triples for
    hover, kind being "gate" or "box"."""
    artists = []
    for tid, t in data.items():
        label = f'{tid} · {t.get("name", "?")}'
        b, g = t.get("bounds"), t.get("gate")
        if b:
            xs, zs = box_xy(b)
            (line,) = ax.plot(xs, zs, color="#9aa0a6", lw=0.7, alpha=0.5, zorder=1)
            line.set_pickradius(PICK_RADIUS_BOX_PT)
            artists.append((line, label, "box"))
        if g:
            p1, p2 = g["p1"], g["p2"]
            (line,) = ax.plot(
                [p1["x"], p2["x"]], [p1["z"], p2["z"]],
                color="#1a1a2e", lw=2.5, solid_capstyle="round", zorder=3,
            )
            line.set_pickradius(PICK_RADIUS_GATE_PT)
            artists.append((line, label, "gate"))
    _style(ax, "All tracks: bounding boxes (gray) and start/finish gates (dark)")
    return artists


def build_brands_hatch(ax, data: dict):
    """Draw the GP/Indy pair; return (artist, label, kind) triples for hover."""
    artists = []
    styles = {
        "119": ("#5B7FDE", "Brands Hatch GP  (bounds 832 x 933 m)"),
        "346": ("#E8833A", "Brands Hatch Indy (bounds 578 x 408 m)"),
    }
    for tid, (color, legend_label) in styles.items():
        t = data[tid]
        hover_label = f'{tid} · {t["name"]}'
        xs, zs = box_xy(t["bounds"])
        (line,) = ax.plot(xs, zs, color=color, lw=2, label=legend_label)
        line.set_pickradius(PICK_RADIUS_BOX_PT)
        artists.append((line, hover_label, "box"))
        ax.fill(xs, zs, color=color, alpha=0.06)
        p1, p2 = t["gate"]["p1"], t["gate"]["p2"]
        (line,) = ax.plot(
            [p1["x"], p2["x"]], [p1["z"], p2["z"]],
            color=color, lw=5, solid_capstyle="round", zorder=3,
        )
        line.set_pickradius(PICK_RADIUS_GATE_PT)
        artists.append((line, hover_label, "gate"))

    g = data["119"]["gate"]
    gx = (g["p1"]["x"] + g["p2"]["x"]) / 2
    gz = (g["p1"]["z"] + g["p2"]["z"]) / 2
    ax.annotate("shared gate\n(both PX)", xy=(gx, gz), xytext=(gx + 120, gz - 30),
                fontsize=10, color="#1a1a2e",
                arrowprops=dict(arrowstyle="->", color="#1a1a2e", lw=1))
    ax.annotate("GP-only territory\n(z > -58: outside Indy bounds)",
                xy=(150, 200), fontsize=10, color="#5B7FDE", ha="center")

    _style(ax, "Brands Hatch: GP vs Indy share one gate; Indy's box is smaller")
    ax.legend(loc="lower right", frameon=False)
    return artists


def attach_interactivity(fig, ax, artists):
    """Hover tooltips (track names under the cursor), scroll-wheel zoom
    centred on the cursor, and 'r' to reset the view. Returns the tooltip
    annotation (handy for tests)."""
    tooltip = ax.annotate(
        "", xy=(0, 0), xytext=(14, 14), textcoords="offset points",
        bbox=dict(boxstyle="round,pad=0.4", fc="#fffbe6", ec="#999999", alpha=0.95),
        fontsize=9, zorder=10, visible=False, annotation_clip=False,
    )
    home = {"xlim": None, "ylim": None}

    def remember_home():
        if home["xlim"] is None:
            home["xlim"] = ax.get_xlim()
            home["ylim"] = ax.get_ylim()

    def on_move(event):
        if event.inaxes is not ax:
            if tooltip.get_visible():
                tooltip.set_visible(False)
                fig.canvas.draw_idle()
            return
        # Gates first (they carry the identity); box edges after, marked as
        # such — zoomed out, the pick radius spans tens of metres and many
        # unrelated box edges pass under the cursor.
        gate_hits, box_hits = [], []
        for artist, label, kind in artists:
            hit, _ = artist.contains(event)
            if not hit:
                continue
            if kind == "gate":
                if label not in gate_hits:
                    gate_hits.append(label)
            elif label not in box_hits:
                box_hits.append(label)
        names = gate_hits + [
            f"{label}  (box edge)" for label in box_hits if label not in gate_hits
        ]
        if names:
            if len(names) > TOOLTIP_MAX_NAMES:
                names = names[:TOOLTIP_MAX_NAMES] + [f"… +{len(names) - TOOLTIP_MAX_NAMES} more"]
            tooltip.xy = (event.xdata, event.ydata)
            tooltip.set_text("\n".join(names))
            tooltip.set_visible(True)
            fig.canvas.draw_idle()
        elif tooltip.get_visible():
            tooltip.set_visible(False)
            fig.canvas.draw_idle()

    def on_scroll(event):
        if event.inaxes is not ax or event.xdata is None:
            return
        remember_home()
        # Same factor on both axes keeps the 1:1 aspect intact.
        scale = 1 / 1.25 if event.button == "up" else 1.25
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        xd, yd = event.xdata, event.ydata
        ax.set_xlim(xd - (xd - x0) * scale, xd + (x1 - xd) * scale)
        ax.set_ylim(yd - (yd - y0) * scale, yd + (y1 - yd) * scale)
        fig.canvas.draw_idle()

    def on_key(event):
        if event.key == "r" and home["xlim"] is not None:
            ax.set_xlim(home["xlim"])
            ax.set_ylim(home["ylim"])
            fig.canvas.draw_idle()

    fig.canvas.mpl_connect("motion_notify_event", on_move)
    fig.canvas.mpl_connect("scroll_event", on_scroll)
    fig.canvas.mpl_connect("key_press_event", on_key)
    return tooltip


def print_analysis(data: dict) -> None:
    for tid in ("119", "346"):
        t = data.get(tid)
        if t is None:
            continue
        b = t["bounds"]
        print(f'{t["name"]:35s} dir={t["gate"]["direction"]}  '
              f'gate p1=({t["gate"]["p1"]["x"]:.1f},{t["gate"]["p1"]["z"]:.1f})  '
              f'area={area(b)/1e3:.0f}k m^2  '
              f'bounds z=[{b["min_z"]:.1f},{b["max_z"]:.1f}] x=[{b["min_x"]:.1f},{b["max_x"]:.1f}]')

    print(f"\nGate-sharing groups (midpoints within {GATE_GROUP_RADIUS_M:.0f} m):")
    for grp in gate_groups(data):
        print("  " + " | ".join(
            f'{data[t]["name"]} [{data[t]["gate"]["direction"]}]' for t in grp
        ))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Plot the track-identification database (bounds + gates).",
    )
    parser.add_argument(
        "-i", "--interactive", action="store_true",
        help="open interactive windows (scroll = zoom at cursor, hover = "
             "track-name tooltip, r = reset view) instead of writing PNGs",
    )
    args = parser.parse_args(argv)

    import matplotlib

    if not args.interactive:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = load_data()

    fig1, ax1 = plt.subplots(figsize=(11, 11))
    overview_artists = build_overview(ax1, data)
    fig1.tight_layout()

    fig2, ax2 = plt.subplots(figsize=(9, 9))
    brands_artists = build_brands_hatch(ax2, data)
    fig2.tight_layout()

    print_analysis(data)

    if args.interactive:
        attach_interactivity(fig1, ax1, overview_artists)
        attach_interactivity(fig2, ax2, brands_artists)
        plt.show()
    else:
        fig1.savefig(HERE / "overview.png", dpi=110)
        fig2.savefig(HERE / "brands_hatch.png", dpi=110)
        print(f"\nWrote {HERE / 'overview.png'}")
        print(f"Wrote {HERE / 'brands_hatch.png'}")


if __name__ == "__main__":
    main()
