"""Compose the simulation setup figure from the included MuJoCo renders."""
from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
meta = json.loads((ROOT / "results/simulation-scene-provenance.json").read_text())
plt.rcParams.update({"font.family": "DejaVu Sans", "pdf.fonttype": 42, "savefig.bbox": None})
fig = plt.figure(figsize=(12.2, 5.65), facecolor="white")
overview = fig.add_axes([.005, .015, .745, .90])
detail = fig.add_axes([.785, .015, .215, .90])
for ax, entry in zip([overview, detail], meta["images"]):
    ax.imshow(Image.open(ROOT / entry["path"]))
    ax.axis("off")
fig.text(.008, .96, "(a) Simulation lobby and original start", fontsize=17, color="#182b3b")
fig.text(.785, .96, "(b) Target panel", fontsize=17, color="#182b3b")

style = dict(fontsize=16, color="#182b3b", ha="center", va="center",
             bbox=dict(boxstyle="round,pad=.3", facecolor="white", edgecolor="none", alpha=.94),
             arrowprops=dict(arrowstyle="->", color="#b55a12", lw=1.8))
target = meta["images"][0]["target_pixel"]
overview.add_patch(Circle(target, 13, fill=False, edgecolor="#b55a12", lw=1.8))
overview.annotate("Target: UP button", xy=(target[0], target[1]-13),
                  xytext=(target[0]+80, target[1]-175), **style)
overview.annotate("Original start", xy=meta["images"][0]["robot_pixel"],
                  xytext=(880, 865), **style)
target = meta["images"][1]["target_pixel"]
detail.add_patch(Circle(target, 118, fill=False, edgecolor="#b55a12", lw=2.2))
detail.annotate("UP (target)", xy=(target[0], target[1]-118),
                xytext=(target[0], 45), **style)
out = ROOT / "paper/figures"
fig.savefig(out / "simulation-scene.pdf", facecolor="white")
fig.savefig(out / "simulation-scene.png", facecolor="white", dpi=190)
plt.close(fig)
print("Simulation setup figure rebuilt from included scene renders.")
