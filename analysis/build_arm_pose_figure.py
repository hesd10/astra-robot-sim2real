"""Assemble the recorded-pose comparison from included offline renders."""
from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
rows = json.loads((ROOT / "results/arm-pose-provenance.json").read_text())["images"]
plt.rcParams.update({"font.family": "DejaVu Sans", "pdf.fonttype": 42,
                     "savefig.bbox": None})
fig, axes = plt.subplots(1, 3, figsize=(12, 4.7))
titles = ["(a) Initial arm configuration", "(b) Pose found in the source", "(c) Pose reused in an E3 trial"]
for ax, row, title in zip(axes, rows, titles):
    ax.imshow(Image.open(ROOT / row["path"]))
    ax.set_title(title, fontsize=12, pad=10)
    ax.axis("off")
    ax.text(.5, -.035, f"{row['time_seconds']:.0f} s into the episode",
            ha="center", va="top", transform=ax.transAxes, fontsize=11)
    if row["label"] != "initial":
        ax.text(.5, -.108, r"Targets: $(q_2,q_3,q_4)=(1.0,1.2,-0.84)$ rad",
                ha="center", va="top", transform=ax.transAxes, fontsize=10)
fig.subplots_adjust(left=.01, right=.99, bottom=.14, top=.91, wspace=.035)
for suffix in ["pdf", "png"]:
    fig.savefig(ROOT / "paper/figures" / f"arm-pose-reuse.{suffix}", dpi=190)
plt.close(fig)
print("Built recorded arm-pose comparison.")
