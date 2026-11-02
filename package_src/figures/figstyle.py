# ==== FIGSTYLE v1.2 — DO NOT EDIT; copy this entire block verbatim ====
import re
from itertools import combinations
from pathlib import Path

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.collections import PathCollection
from matplotlib.text import Text
from matplotlib.transforms import Bbox

FIGSTYLE_VERSION = "1.2"

# Series colors (Okabe-Ito based, order validated for color-vision deficiency). Assign in this order only; never cycle.
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#56B4E9", "#CC79A7"]
MARKERS = ["o", "s", "^", "D", "v", "P"]
LINESTYLES = ["-", "--", "-.", ":", (0, (5, 1)), (0, (3, 1, 1, 1))]
INK = "#000000"     # text, axes, reference lines
MUTED = "#7F7F7F"   # secondary elements (guide lines, inactive data)
CMAP_SEQ = "viridis"   # magnitude (one-directional) values
CMAP_DIV = "RdBu_r"    # signed values (center at 0 with TwoSlopeNorm)

# Presets per medium: sizes are final output size (inch), fonts are final size (pt)
MEDIA = {
    "paper":  dict(widths={"single": 3.5, "onehalf": 5.5, "double": 7.0},
                   base=8,  small=7,  panel=10, line=1.0, axis=0.6,
                   marker=4,  aspect=0.75),
    "slide":  dict(widths={"single": 6.0, "onehalf": 9.0, "double": 12.0},
                   base=18, small=16, panel=20, line=2.5, axis=1.2,
                   marker=8,  aspect=0.5625),
    "poster": dict(widths={"single": 8.0, "onehalf": 12.0, "double": 16.0},
                   base=28, small=24, panel=32, line=3.5, axis=1.8,
                   marker=11, aspect=0.66),
    "explore": dict(widths={"single": 6.4, "onehalf": 8.0, "double": 10.0},
                    base=10, small=9,  panel=12, line=1.5, axis=0.8,
                    marker=5,  aspect=0.62),
}

_FONT_CANDIDATES = ["Arial", "Liberation Sans", "Helvetica", "DejaVu Sans"]
_ALLOW_GID = "figstyle-allow-overlap"


def _pick_font():
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in _FONT_CANDIDATES:
        if name in available:
            if name != "Arial":
                print(f"[figstyle] Arial not found -> using '{name}' (installing Arial is recommended)")
            return name
    return "DejaVu Sans"


def apply_style(medium="paper"):
    """Call once, after importing seaborn and before drawing."""
    m = MEDIA[medium]
    font = _pick_font()
    mpl.rcdefaults()
    mpl.rcParams.update({
        # Fonts
        "font.family": "sans-serif",
        "font.sans-serif": [font] + _FONT_CANDIDATES,
        "font.size": m["base"],
        "axes.labelsize": m["base"],
        "axes.titlesize": m["base"],
        "xtick.labelsize": m["small"],
        "ytick.labelsize": m["small"],
        "legend.fontsize": m["small"],
        "legend.title_fontsize": m["small"],
        # Math: upright by default (numbers, units, descriptive subscripts); var() italicizes variables via \mathit
        "mathtext.fontset": "custom",
        "mathtext.rm": font,
        "mathtext.it": f"{font}:italic",
        "mathtext.bf": f"{font}:bold",
        "mathtext.sf": font,
        "mathtext.cal": font,
        "mathtext.default": "regular",
        "axes.unicode_minus": True,
        # Tick numbers: no '1e3'/offset text at the axis end; rescale units via axis_label instead
        "axes.formatter.useoffset": False,
        "axes.formatter.use_mathtext": True,
        "axes.formatter.limits": (-3, 4),
        # Colors
        "axes.prop_cycle": mpl.cycler(color=PALETTE),
        "text.color": INK, "axes.labelcolor": INK, "axes.edgecolor": INK,
        "xtick.color": INK, "ytick.color": INK,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "image.cmap": CMAP_SEQ,
        # Lines and markers
        "lines.linewidth": m["line"],
        "lines.markersize": m["marker"],
        "lines.markeredgewidth": m["axis"],
        "patch.linewidth": m["axis"],
        "errorbar.capsize": m["marker"] * 0.6,
        # Axes
        "axes.linewidth": m["axis"],
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": False,
        "axes.titlelocation": "left",
        "axes.labelpad": m["base"] * 0.4,
        "xtick.direction": "out", "ytick.direction": "out",
        "xtick.major.width": m["axis"], "ytick.major.width": m["axis"],
        "xtick.minor.width": m["axis"] * 0.7, "ytick.minor.width": m["axis"] * 0.7,
        "xtick.major.size": m["base"] * 0.4, "ytick.major.size": m["base"] * 0.4,
        "xtick.minor.size": m["base"] * 0.25, "ytick.minor.size": m["base"] * 0.25,
        # Legend
        "legend.frameon": False,
        "legend.handlelength": 1.8,
        "legend.borderaxespad": 0.3,
        # Layout and saving
        "figure.dpi": 100,
        "figure.constrained_layout.use": True,
        "savefig.dpi": 600,
        "savefig.bbox": "standard",   # no 'tight': keeps the final size fixed
        "svg.fonttype": "none",       # keep SVG text editable
        "svg.hashsalt": "figstyle",   # reproducible SVG output
    })
    globals()["_MEDIUM"] = medium


# ---------- Notation ----------
def var(symbol, sub=None, sub_is_var=False):
    """Variable symbol. var("C", "fish") -> C (italic) + fish (upright subscript).
    Greek letters: var(r"\\alpha"). If the subscript is itself a variable (index i), sub_is_var=True."""
    s = rf"\mathit{{{symbol}}}"
    if sub is not None:
        s += rf"_{{\mathit{{{sub}}}}}" if sub_is_var else rf"_{{\mathrm{{{sub}}}}}"
    return f"${s}$"


def unit(spec):
    """Unit string. Write exponents as digits right after the symbol: unit("µg kg-1 d-1") -> µg kg⁻¹ d⁻¹."""
    out = []
    for tok in spec.split():
        mt = re.fullmatch(r"(.*?[^\d\-])(-?\d+)", tok)
        out.append(f"{mt.group(1)}$^{{{mt.group(2)}}}$" if mt else tok)
    return " ".join(out)


def axis_label(quantity, unit_spec=None, scale=None):
    """Axis label 'Quantity (unit)'. scale=3 -> (×10³ unit). Dimensionless: unit_spec=None."""
    if unit_spec is None and scale is None:
        return quantity
    parts = []
    if scale is not None:
        parts.append(f"×10$^{{{scale}}}$")
    if unit_spec:
        parts.append(unit(unit_spec))
    return f"{quantity} ({' '.join(parts)})"


# ---------- Figure creation ----------
def new_figure(width="single", aspect=None, nrows=1, ncols=1, **kwargs):
    """width: 'single' | 'onehalf' | 'double' or a number in inches. aspect = height/width."""
    m = MEDIA[globals().get("_MEDIUM", "paper")]
    w = m["widths"][width] if isinstance(width, str) else float(width)
    h = w * (aspect if aspect is not None else m["aspect"])
    return plt.subplots(nrows, ncols, figsize=(w, h), **kwargs)


def panel_labels(axes, start="a"):
    """Add bold (a), (b), ... outside the top-left corner of each panel."""
    m = MEDIA[globals().get("_MEDIUM", "paper")]
    axes = list(getattr(axes, "flat", [axes]))
    for i, ax in enumerate(axes):
        ax.text(-0.02, 1.02, f"({chr(ord(start) + i)})", transform=ax.transAxes,
                ha="right", va="bottom", fontsize=m["panel"], fontweight="bold")


def allow_overlap(*artists):
    """Exempt text deliberately placed on data (bar value labels, heatmap cell numbers) from the check."""
    for a in artists:
        a.set_gid(_ALLOW_GID)


# ---------- Overlap check ----------
def _texts(fig):
    """List of (name, Text, parent axes or None). Only visible, non-empty text."""
    items = []

    def add(name, t, ax):
        if isinstance(t, Text) and t.get_visible() and t.get_text().strip():
            items.append((name, t, ax))

    add("suptitle", getattr(fig, "_suptitle", None), None)
    for t in fig.texts:
        add("figure text", t, None)
    for i, ax in enumerate(fig.axes):
        if not ax.get_visible():
            continue
        tag = f"axes[{i}]"
        add(f"{tag} title", ax.title, ax)
        add(f"{tag} title(left)", ax._left_title, ax)
        add(f"{tag} title(right)", ax._right_title, ax)
        add(f"{tag} xlabel", ax.xaxis.label, ax)
        add(f"{tag} ylabel", ax.yaxis.label, ax)
        add(f"{tag} x offset", ax.xaxis.offsetText, ax)
        add(f"{tag} y offset", ax.yaxis.offsetText, ax)
        for axis, nm in ((ax.xaxis, "x"), (ax.yaxis, "y")):
            lo, hi = sorted(axis.get_view_interval())
            for tick in axis.get_major_ticks() + axis.get_minor_ticks():
                if lo - 1e-9 * (hi - lo + 1) <= tick.get_loc() <= hi + 1e-9 * (hi - lo + 1):
                    add(f"{tag} {nm}tick '{tick.label1.get_text()}'", tick.label1, ax)
                    add(f"{tag} {nm}tick '{tick.label2.get_text()}'", tick.label2, ax)
        for t in ax.texts:
            add(f"{tag} text '{t.get_text()[:20]}'", t, ax)
    return items


def _data_shapes(ax, renderer):
    """Data elements in an axes as (name, display-space Path or list of point bboxes, filled)."""
    shapes = []
    for ln in ax.lines:
        if not ln.get_visible():
            continue
        path = ln.get_transform().transform_path(ln.get_path())
        if ln.get_linestyle() not in ("None", "none", "", " ") and len(path.vertices) > 1:
            shapes.append((f"line '{ln.get_label()}'", path, False))
        if ln.get_marker() not in (None, "None", "none", "", " "):
            r = ln.get_markersize() * ax.figure.dpi / 72 / 2
            boxes = [Bbox.from_extents(x - r, y - r, x + r, y + r)
                     for x, y in path.vertices if np.isfinite([x, y]).all()]
            shapes.append((f"markers '{ln.get_label()}'", boxes, None))
    for p in ax.patches:
        if p.get_visible():
            path = p.get_transform().transform_path(p.get_path())
            shapes.append((f"patch {type(p).__name__}", path, p.get_fill()))
    for c in ax.collections:
        if not c.get_visible():
            continue
        if isinstance(c, PathCollection) and len(c.get_offsets()):
            pts = c.get_offset_transform().transform(c.get_offsets())
            sizes = c.get_sizes() if len(c.get_sizes()) else [36]
            boxes = []
            for k, (x, y) in enumerate(pts):
                r = np.sqrt(sizes[k % len(sizes)]) * ax.figure.dpi / 72 / 2
                if np.isfinite([x, y]).all():
                    boxes.append(Bbox.from_extents(x - r, y - r, x + r, y + r))
            shapes.append((f"scatter '{c.get_label()}'", boxes, None))
        else:
            filled = len(c.get_facecolors()) > 0 and np.any(np.asarray(c.get_facecolors())[:, 3] > 0)
            for path in c.get_paths():
                shapes.append((f"{type(c).__name__}",
                               c.get_transform().transform_path(path), filled))
    return shapes


def _hits(bb, shape):
    _, geom, filled = shape
    if isinstance(geom, list):
        return any(bb.overlaps(b) for b in geom)
    return geom.intersects_bbox(bb, filled=bool(filled))


def check_layout(fig, pad_pt=1.0):
    """Check text-text, text-data, text outside the figure, and forbidden offset text; return a list of issues."""
    fig.draw_without_rendering()
    renderer = fig.canvas.get_renderer()
    pad = pad_pt * fig.dpi / 72
    W, H = fig.bbox.width, fig.bbox.height
    texts = [(n, t, ax, t.get_window_extent(renderer)) for n, t, ax in _texts(fig)]
    issues = []

    # 1) Forbidden offset/multiplier text (violates the rescale-units rule)
    for n, t, ax, bb in texts:
        if n.endswith("offset"):
            issues.append(f"[notation] {n} '{t.get_text()}' — change the unit or move it into axis_label(scale=)")

    # 2) Text clipped by the figure boundary
    for n, t, ax, bb in texts:
        if bb.x0 < -0.5 or bb.y0 < -0.5 or bb.x1 > W + 0.5 or bb.y1 > H + 0.5:
            issues.append(f"[clipped] {n} — extends beyond the figure boundary")

    # 3) Text-text overlap (a legend counts as one box)
    boxes = [(n, bb) for n, t, ax, bb in texts]
    for i, ax in enumerate(fig.axes):
        lg = ax.get_legend()
        if lg is not None and lg.get_visible():
            boxes.append((f"axes[{i}] legend", lg.get_window_extent(renderer)))
    if fig.legends:
        for lg in fig.legends:
            boxes.append(("figure legend", lg.get_window_extent(renderer)))
    for (n1, b1), (n2, b2) in combinations(boxes, 2):
        if b1.padded(pad / 2).overlaps(b2.padded(pad / 2)):
            issues.append(f"[text overlap] {n1} <-> {n2}")

    # 4) Text/legend-data overlap (data is visible only inside the axes, so test only the part inside it)
    targets = [(n, t, bb) for n, t, ax, bb in texts if t.get_gid() != _ALLOW_GID]
    for i, ax in enumerate(fig.axes):
        lg = ax.get_legend()
        if lg is not None and lg.get_visible():
            targets.append((f"axes[{i}] legend", lg, lg.get_window_extent(renderer)))
    for i, ax in enumerate(fig.axes):
        if not ax.get_visible():
            continue
        shapes = _data_shapes(ax, renderer)
        for n, t, bb in targets:
            inter = Bbox.intersection(bb.padded(pad), ax.bbox)
            if inter is None or inter.width <= 0 or inter.height <= 0:
                continue
            for s in shapes:
                if _hits(inter, s):
                    issues.append(f"[data overlap] {n} <-> axes[{i}] {s[0]}")
    return issues


class FigstyleLayoutError(RuntimeError):
    pass


def save_figure(fig, name, outdir="figures", check=True):
    """If the overlap check passes, save figures/<name>.svg and .png (600 dpi) together."""
    if check:
        issues = check_layout(fig)
        if issues:
            raise FigstyleLayoutError(
                f"'{name}': {len(issues)} layout issue(s) — fix them and save again:\n  "
                + "\n  ".join(dict.fromkeys(issues)))
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    meta_svg = {"Date": None, "Creator": f"figstyle v{FIGSTYLE_VERSION}"}
    meta_png = {"Software": f"figstyle v{FIGSTYLE_VERSION}"}
    fig.savefig(out / f"{name}.svg", metadata=meta_svg)
    fig.savefig(out / f"{name}.png", dpi=600, metadata=meta_png)
    print(f"[figstyle] saved: {out / name}.svg/.png (overlap check {'passed' if check else 'skipped'})")
    return out / f"{name}.svg", out / f"{name}.png"
# ==== END FIGSTYLE v1.2 ====
