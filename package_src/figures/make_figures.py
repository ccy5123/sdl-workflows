"""Figures 1-4 of the manuscript, from the database build and the analysis outputs.

Usage (from the workspace root, Python with matplotlib and seaborn):
  python package_src/figures/make_figures.py
Writes package_src/figures/fig<n>_*.svg and .png (600 dpi).
"""
import csv
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import seaborn as sns  # noqa: F401  (imported before apply_style, as FIGSTYLE requires)
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from figstyle import (INK, MUTED, PALETTE, MARKERS, LINESTYLES, CMAP_SEQ, allow_overlap, apply_style,  # noqa: E402
                      axis_label, new_figure, panel_labels, save_figure)

apply_style("paper")
OUT = HERE

# One color per transfer mode in every figure (PALETTE order).
MODES = ["fixed_tubing", "robot_arm_gantry", "mobile_robot", "human_transfer", "data_transfer", "unmapped"]
MODE_NAME = {"fixed_tubing": "Fixed tubing", "robot_arm_gantry": "Robot arm or gantry", "mobile_robot": "Mobile robot",
             "human_transfer": "Human transfer", "data_transfer": "Data transfer", "unmapped": "Unmapped"}
MODE_COLOR = {m: PALETTE[i] for i, m in enumerate(MODES)}
MODE_STYLE = {m: LINESTYLES[i] for i, m in enumerate(MODES)}


# ---------------------------------------------------------------- Figure 1
def fig1():
    db = sqlite3.connect(ROOT / "db/sdl-db.sqlite")
    pid = "Luo2025/P1"
    steps = db.execute("SELECT step_id, unit_operation, primary_module_id, primary_module_type, performed_by, "
                       "on_platform FROM v_step WHERE platform_id=? ORDER BY step_order", (pid,)).fetchall()
    conns = db.execute("SELECT from_module, to_module, transfer_mode FROM v_connection WHERE platform_id=?",
                       (pid,)).fetchall()
    op = {"dispense_liquid": "dispense\nliquid", "handle_sample": "handle\nsample", "react_thermal": "thermal\nreaction",
          "centrifuge": "centrifuge", "evaporate_dry": "evaporate,\ndry", "measure_optical": "optical\nmeasure",
          "analyze_data": "analyze\ndata", "plan_next_experiment": "plan next\nexperiment"}
    mt = {"liquid_handler": "liquid handler", "sample_handling_station": "sample-handling\nstation",
          "batch_reactor": "batch reactor", "separation_unit": "separation unit", "human": "person",
          "instrument_optical": "optical instrument", "software": "software"}
    fig, ax = new_figure("double", aspect=0.43)
    ax.set_xlim(0, 10.45)
    ax.set_ylim(0.3, 4.05)
    ax.axis("off")
    # Steps snake through two rows: S1-S5 left to right, S6-S9 right to left, so the loop closes at the left.
    per_row, pitch, w, h = 5, 2.2, 1.35, 1.05
    rows_y = (2.65, 0.75)
    pos = []
    for i in range(len(steps)):
        r, k = divmod(i, per_row)
        pos.append((0.15 + (k if r == 0 else per_row - 1 - k) * pitch, rows_y[r], r))
    mod_step = {}
    for i, (sid, uo, mid, mtype, perf, onp) in enumerate(steps):
        x, y, _ = pos[i]
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.06", facecolor="white",
                             edgecolor=INK, linewidth=0.8, linestyle="-" if onp else (0, (3, 2)))
        ax.add_patch(box)
        t1 = ax.text(x + w / 2, y + h - 0.1, op.get(uo, uo), ha="center", va="top", fontsize=7, fontweight="bold")
        t2 = ax.text(x + w / 2, y + 0.1, mt.get(mtype, mtype), ha="center", va="bottom", fontsize=7)
        t3 = ax.text(x + w, y + h + 0.08, {"robot": "robot", "human": "person"}.get(perf, perf),
                     ha="right", va="bottom", fontsize=7, color=MUTED)
        t4 = ax.text(x, y + h + 0.08, f"S{i + 1}", ha="left", va="bottom", fontsize=7)
        allow_overlap(t1, t2)
        mod_step.setdefault(mid, []).append(i)
    for a, b, mode in conns:
        ia, ib = mod_step[a][-1], mod_step[b][0]
        kw = dict(arrowstyle="-|>", color=MODE_COLOR[mode], lw=1.4, linestyle=MODE_STYLE[mode],
                  shrinkA=0, shrinkB=0, mutation_scale=8)
        (xa, ya, ra), (xb, yb, rb) = pos[ia], pos[ib]
        if ib == ia + 1 and ra == rb == 0:
            ax.annotate("", xy=(xb, yb + h / 2), xytext=(xa + w, ya + h / 2), arrowprops=kw)
        elif ib == ia + 1 and ra == rb == 1:
            ax.annotate("", xy=(xb + w, yb + h / 2), xytext=(xa, ya + h / 2), arrowprops=kw)
        elif ib == ia + 1:  # down from the end of the first row to the start of the second
            ax.annotate("", xy=(xb + w / 2, yb + h), xytext=(xa + w / 2, ya), arrowprops=kw)
        else:  # the connection that closes the loop
            kw["connectionstyle"] = "angle,angleA=180,angleB=90,rad=0"
            ax.annotate("", xy=(xb + w / 2, yb), xytext=(xa, ya + h / 2), arrowprops=kw)
    handles = [Line2D([], [], color=MODE_COLOR[m], linestyle=MODE_STYLE[m], lw=1.4, label=MODE_NAME[m])
               for m in MODES if m in {c[2] for c in conns}]
    handles += [Patch(facecolor="white", edgecolor=INK, lw=0.8, label="Module on the platform"),
                Patch(facecolor="white", edgecolor=INK, lw=0.8, linestyle=(0, (3, 2)),
                      label="Module apart from the platform")]
    fig.legend(handles=handles, loc="outside lower center", ncol=3)
    return save_figure(fig, "fig1_coded_platform_paper", outdir=OUT)


# ---------------------------------------------------------------- Figure 3
def fig_throughput():
    r = json.loads((ROOT / "reproduction/03_throughput/out/throughput/results.json").read_text())
    own = r["per_paper"]["reproduction_own_durations"]
    fig, axes = new_figure("double", aspect=0.46, ncols=2)
    vals = [v[k] for v in own.values() for k in ("reported", "simulated", "serial_sum") if v.get(k)]
    lo, hi = min(vals) / 2, max(vals) * 2
    grid = np.geomspace(lo, hi, 50)
    kinds = [("measured", "Measured during a campaign"), ("nominal", "Nominal capacity")]
    for ax, key, ylab in ((axes[0], "simulated", "Simulated throughput"),
                          (axes[1], "serial_sum", "Sum-of-durations estimate")):
        ax.fill_between(grid, grid / 1.5, grid * 1.5, color=MUTED, alpha=0.2, linewidth=0,
                        label="Within a factor of 1.5")
        ax.plot(grid, grid, color=MUTED, lw=0.8, linestyle="--", label="Equal")
        for i, (kind, name) in enumerate(kinds):
            pts = [(v["reported"], v[key]) for v in own.values() if v["kind"] == kind and v.get(key)]
            x, y = zip(*pts)
            ax.plot(x, y, linestyle="none", marker=MARKERS[i], color=PALETTE[i], markersize=4,
                    markeredgecolor="white", markeredgewidth=0.4, label=name)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel(axis_label("Reported throughput", "experiments d-1"))
        ax.set_ylabel(axis_label(ylab, "experiments d-1"))
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=4)
    panel_labels(axes)
    return save_figure(fig, "fig4_throughput_paper", outdir=OUT)


# ---------------------------------------------------------------- Figure 2
def fig_transfer():
    counts = {}
    with open(ROOT / "reproduction/06_further_analyses/out/config_class_counts.csv") as f:
        for row in csv.DictReader(f):
            if row["label"] == "transfer_mode":
                counts[row["value"]] = (float(row["fitting_share"]), float(row["evaluation_share"]))
    rows = [m for m in MODES if m in counts]
    conf = Counter()
    with open(ROOT / "reproduction/02_configuration_prediction/out/evaluation/predictions.csv") as f:
        for row in csv.DictReader(f):
            if row["set"] == "evaluated" and row["label"] == "transfer_mode":
                conf[(row["y"], row["model_top1"])] += 1
    fig, axes = new_figure("double", aspect=0.42, ncols=2, gridspec_kw={"width_ratios": [1, 1.1]})
    ax = axes[0]
    yy = np.arange(len(rows))
    hgt = 0.38
    for i, (lab, col) in enumerate((("Papers up to 2023 (training)", 0), ("Papers from 2024 (evaluation)", 1))):
        ax.barh(yy + (i - 0.5) * hgt, [counts[m][col] for m in rows], height=hgt, color=PALETTE[i], label=lab)
    ax.set_yticks(yy, [MODE_NAME[m] for m in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, 0.62)
    ax.set_xlabel(axis_label("Share of material connections"))
    ax.legend(loc="lower right")
    ax = axes[1]
    pred = [m for m in rows if any(conf[(t, m)] for t in rows)]
    mat = np.array([[conf[(t, p)] for p in pred] for t in rows])
    im = ax.imshow(mat, cmap=CMAP_SEQ, aspect="auto")
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            t = ax.text(j, i, str(mat[i, j]), ha="center", va="center", fontsize=7,
                        color="white" if mat[i, j] < mat.max() * 0.6 else INK)
            allow_overlap(t)
    two_line = {"fixed_tubing": "Fixed\ntubing", "robot_arm_gantry": "Robot arm\nor gantry", "mobile_robot": "Mobile\nrobot",
                "human_transfer": "Human\ntransfer", "unmapped": "Unmapped"}
    ax.set_xticks(range(len(pred)), [two_line[m] for m in pred])
    ax.set_yticks(range(len(rows)), [MODE_NAME[m] for m in rows])
    ax.set_xlabel("Predicted by the model")
    ax.set_ylabel("Recorded")
    for s in ("top", "right"):
        ax.spines[s].set_visible(True)
    cb = fig.colorbar(im, ax=ax, shrink=0.9)
    cb.set_label(axis_label("Connections"))
    panel_labels(axes)
    return save_figure(fig, "fig3_transfer_mode_paper", outdir=OUT), int(np.trace(mat)), int(mat.sum())


# ---------------------------------------------------------------- Figure 4
def fig4():
    d = json.loads((ROOT / "reproduction/05_reporting/out/results.json").read_text())
    names = {"durations_every_step": "Durations for every step", "batch_size": "Batch size",
             "planning_time": "Planning time", "operating_time": "Operating time", "any_throughput": "Any throughput",
             "measured_throughput": "Measured throughput", "cost": "Cost", "transfer_time": "Transfer time",
             "human_intervention_number_or_none": "Human intervention,\nnumber or none",
             "longest_unattended_run": "Longest unattended run"}
    items = sorted(names, key=lambda k: -d["items"][k]["share"])
    fig, ax = new_figure("onehalf", aspect=0.62)
    yy = np.arange(len(items))
    sh = np.array([d["items"][k]["share"] for k in items])
    lo = sh - np.array([d["items"][k]["ci95_lo"] for k in items])
    hi = np.array([d["items"][k]["ci95_hi"] for k in items]) - sh
    ax.barh(yy, sh, height=0.6, color=PALETTE[0], label="All papers (95% interval)")
    ax.errorbar(sh, yy, xerr=[lo, hi], fmt="none", ecolor=INK, elinewidth=0.6)
    for i, (key, lab) in enumerate((("share_early", "Up to 2023"), ("share_late", "From 2024"))):
        ax.plot([d["by_period"]["items"][k][key] for k in items], yy + (i - 0.5) * 0.3, linestyle="none",
                marker=MARKERS[i + 1], color=PALETTE[i + 1], markersize=3.5, markeredgecolor=INK,
                markeredgewidth=0.4, label=lab)
    ax.set_yticks(yy, [names[k] for k in items])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel(axis_label("Share of papers reporting the item"))
    ax.legend(loc="lower right")
    return save_figure(fig, "fig5_reporting_paper", outdir=OUT)


# ---------------------------------------------------------------- Figure 2: contents of the database
def fig_overview():
    rel = sqlite3.connect(ROOT / "release/out/sdl-workflows-1.1.0/sdl-workflows.sqlite")
    years = Counter(y for (y,) in rel.execute("SELECT first_public_year FROM paper"))
    labels = ["<2015"] + [str(y) for y in range(2015, 2027)]
    counts = [sum(n for y, n in years.items() if y < 2015)] + [years.get(y, 0) for y in range(2015, 2027)]
    fields = rel.execute("SELECT first_field_tag, count(*) FROM trends_paper GROUP BY 1 ORDER BY 2 DESC").fetchall()
    fname = {"chemistry_synthesis": "Chemistry and synthesis", "nanomaterials": "Nanomaterials",
             "materials_polymer_soft": "Polymer and soft materials", "materials_thin_film": "Thin-film materials",
             "catalysis": "Catalysis", "biology_biochem": "Biology and biochemistry",
             "analytical_chemistry": "Analytical chemistry", "materials_inorganic": "Inorganic materials",
             "battery_electrochem": "Battery and electrochemistry"}
    fam = rel.execute("SELECT u.family, s.performed_by, count(*) FROM step s JOIN unit_operation u "
                      "ON u.unit_operation = s.unit_operation GROUP BY 1, 2").fetchall()
    fams = ["prepare", "mix", "react", "form", "separate", "measure", "handle", "analyze", "plan", "unmapped"]
    performers = [("robot", "Robot"), ("software", "Software"), ("human", "Person")]
    tab = {(f, p): n for f, p, n in fam}
    fig, axes = new_figure("double", aspect=0.40, ncols=3, gridspec_kw={"width_ratios": [1.25, 1, 1]})
    ax = axes[0]
    ax.bar(range(len(counts)), counts, color=PALETTE[0], width=0.75)
    ax.set_xticks(range(len(counts)), labels, rotation=90)
    ax.set_ylabel(axis_label("Papers"))
    ax.set_xlabel("Year first made public")
    ax = axes[1]
    yy = np.arange(len(fields))
    ax.barh(yy, [n for _, n in fields], color=PALETTE[0], height=0.7)
    ax.set_yticks(yy, [fname[f] for f, _ in fields])
    ax.invert_yaxis()
    ax.set_xlabel(axis_label("Papers"))
    ax = axes[2]
    yy = np.arange(len(fams))
    left = np.zeros(len(fams))
    for i, (p, lab) in enumerate(performers):
        vals = np.array([tab.get((f, p), 0) for f in fams])
        ax.barh(yy, vals, left=left, color=PALETTE[i], height=0.7, label=lab)
        left += vals
    ax.set_yticks(yy, fams)
    ax.invert_yaxis()
    ax.set_xlabel(axis_label("Steps"))
    fig.legend(*ax.get_legend_handles_labels(), loc="outside lower center", ncol=3, title="Steps performed by")
    panel_labels(axes)
    return save_figure(fig, "fig2_overview_paper", outdir=OUT)


# ---------------------------------------------------------------- TOC graphic, option C
def toc_c():
    """Real step sequences of 14 platforms beside two results, at the ACS TOC size (3.25 x 1.75 in)."""
    import random
    db = sqlite3.connect(ROOT / "db/sdl-db.sqlite")
    group = {"prepare": "prepare", "mix": "prepare", "react": "react", "form": "react", "separate": "separate",
             "measure": "measure", "handle": "handle", "plan": "plan, analyze", "analyze": "plan, analyze"}
    order = ["prepare", "react", "separate", "measure", "handle", "plan, analyze"]
    gcolor = {g: PALETTE[i] for i, g in enumerate(order)}
    seqs = {}
    for pid, fam in db.execute("SELECT platform_id, family FROM v_step ORDER BY platform_id, step_order"):
        seqs.setdefault(pid, []).append(group.get(fam))
    pool = sorted(p for p, s in seqs.items() if 5 <= len(s) <= 11 and None not in s)
    rows = random.Random(7).sample(pool, 14)
    fig, ax = new_figure(3.25, aspect=1.75 / 3.25)
    fig.set_layout_engine("none")  # panels are placed by hand at this small size
    ax.set_position([0.02, 0.24, 0.50, 0.62])
    for r, pid in enumerate(rows):
        for k, g in enumerate(seqs[pid]):
            ax.add_patch(FancyBboxPatch((k + 0.08, -r + 0.12), 0.84, 0.76, boxstyle="round,pad=0,rounding_size=0.15",
                                        facecolor=gcolor[g], edgecolor="none"))
    ax.set_xlim(0, 11)
    ax.set_ylim(-13.05, 1.05)
    ax.axis("off")
    fig.text(0.02, 0.97, "238 papers, step by step", ha="left", va="top", fontsize=7, fontweight="bold")
    fig.legend(handles=[Patch(facecolor=gcolor[g], label=g) for g in order], loc="lower left",
               bbox_to_anchor=(0.0, 0.0), ncol=3, fontsize=6, handlelength=0.9, handleheight=0.9,
               columnspacing=0.6, handletextpad=0.3, borderaxespad=0.1)
    # throughput, own durations
    r = json.loads((ROOT / "reproduction/03_throughput/out/throughput/results.json").read_text())
    own = r["per_paper"]["reproduction_own_durations"]
    sc = fig.add_axes([0.66, 0.52, 0.31, 0.34])
    pts = [(v["reported"], v["simulated"]) for v in own.values() if v.get("simulated")]
    g = np.geomspace(0.1, 3000, 40)
    sc.fill_between(g, g / 1.5, g * 1.5, color=MUTED, alpha=0.25, linewidth=0)
    sc.plot(g, g, color=MUTED, lw=0.6, linestyle="--")
    x, y = zip(*pts)
    sc.plot(x, y, linestyle="none", marker="o", color=PALETTE[0], markersize=2.2, markeredgewidth=0)
    sc.set_xscale("log")
    sc.set_yscale("log")
    sc.set_xlim(0.1, 3000)
    sc.set_ylim(0.1, 3000)
    sc.set_xticks([])
    sc.set_yticks([])
    sc.minorticks_off()
    sc.set_xlabel("reported", fontsize=6, labelpad=1)
    sc.set_ylabel("simulated", fontsize=6, labelpad=1)
    fig.text(0.60, 0.97, "Throughput", ha="left", va="top", fontsize=7, fontweight="bold")
    # transfer-mode accuracy
    br = fig.add_axes([0.60, 0.06, 0.37, 0.20])
    br.barh([0, 1], [0.512, 0.441], height=0.62, color=[PALETTE[0], PALETTE[1]])
    br.set_xlim(0, 0.75)
    br.set_ylim(1.6, -0.6)
    br.axis("off")
    for yv, lab, v in ((0, "model", 0.512), (1, "baseline", 0.441)):
        br.text(v + 0.02, yv, f"{lab} {v:.2f}", ha="left", va="center", fontsize=6)
    fig.text(0.60, 0.36, "Transfer mode, 2024–", ha="left", va="top", fontsize=7, fontweight="bold")
    # arrow from records to results
    fig.add_artist(__import__("matplotlib.patches", fromlist=["FancyArrowPatch"]).FancyArrowPatch(
        (0.535, 0.55), (0.585, 0.55), transform=fig.transFigure, arrowstyle="-|>", mutation_scale=7,
        color=INK, lw=0.8))
    return save_figure(fig, "toc_c_paper", outdir=OUT)


if __name__ == "__main__":
    which = sys.argv[1:] or ["1", "2", "3", "4", "5"]
    for n in which:
        print(n, {"1": fig1, "2": fig_overview, "3": fig_transfer, "4": fig_throughput, "5": fig4, "toc": toc_c}[n]())
