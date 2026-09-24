"""Assemble a task sequence from released simulation renders."""
from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
rows = json.loads((ROOT / "results/simulation-sequence-provenance.json").read_text())["images"]
plt.rcParams.update({"font.family": "DejaVu Sans", "pdf.fonttype": 42})
fig, axes = plt.subplots(2, 3, figsize=(12, 7.35))
titles = ["Start", "Advance and unfold", "Extend the arm", "Approach the panel", "Final alignment", "Button activated"]
for i, (ax, row, title) in enumerate(zip(axes.flat, rows, titles)):
    ax.imshow(Image.open(ROOT / row["path"]))
    ax.set_title(f"({chr(97 + i)}) {title}  |  {row['time_seconds']:.0f} s", fontsize=13, pad=8)
    ax.axis("off")
    xy = row["target_pixel"]
    ax.add_patch(Circle(xy, 17, fill=False, edgecolor="#006d77", linewidth=1.1))
    if i == 0:
        ax.annotate("Target button", xy=xy, xytext=(xy[0] - 240, xy[1] - 85),
                    fontsize=10, color="#124452",
                    bbox=dict(boxstyle="round,pad=.25", fc="white", ec="none", alpha=.9),
                    arrowprops=dict(arrowstyle="-", color="#006d77", lw=1))
    if "inset" in row:
        inset = ax.inset_axes([.025, .035, .44, .43])
        inset.imshow(Image.open(ROOT / row["inset"]["path"]))
        inset.set_xticks([]); inset.set_yticks([])
        for spine in inset.spines.values():
            spine.set_edgecolor("white"); spine.set_linewidth(1.8)
fig.subplots_adjust(left=.008, right=.992, bottom=.012, top=.95, wspace=.035, hspace=.12)
for suffix in ("pdf", "png"):
    fig.savefig(ROOT / "paper/figures" / f"simulation-sequence.{suffix}", dpi=220)
plt.close(fig)
print("Built six-frame simulation task sequence.")
