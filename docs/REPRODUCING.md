# Reproducing the results

Run commands from the repository root. The analysis uses the released trial-level JSON files and included images; new agent trials use the simulation or hardware environments described below.

## Rebuild figures and tables

Use Python 3.10 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r analysis/requirements.txt
python analysis/build_results.py
python analysis/build_prompt_appendix.py
python analysis/audit_behavior.py
python analysis/check_release.py
```

These offline commands regenerate ten figure sets, the full fixed-start table, summary statistics, and the prompt appendix, then check the behavioral evidence and release data. `analysis/build_teaser.py` rebuilds the opening result figure on its own. [Teaser provenance](../results/teaser-provenance.json) records the source images and exact comparisons.

The prompt appendix is transcribed from the three frozen task prompts, with LaTeX escaping and typesetting applied by `analysis/build_prompt_appendix.py`. [Prompt provenance](../results/prompt-provenance.json) lists the source paths and checksums.

## Render the recorded simulation states

The included renders can be regenerated in the simulation environment installed below. These scripts restore saved configurations and use MuJoCo forward kinematics without advancing physics.

| Illustration | Renderer | Figure assembly | Source/provenance |
|---|---|---|---|
| Lobby and target panel | `analysis/render_simulation_scene.py` | `analysis/build_scene_figure.py` | [Scene record](../results/simulation-scene-provenance.json) |
| Arm-pose reuse | `analysis/render_arm_poses.py` | `analysis/build_arm_pose_figure.py` | [Selected states](../results/arm-pose-snapshots.json), [render record](../results/arm-pose-provenance.json) |
| Complete task sequence | `analysis/render_simulation_sequence.py` | `analysis/build_simulation_sequence.py` | [Selected states](../results/simulation-sequence-snapshots.json), [render record](../results/simulation-sequence-provenance.json) |

For example:

```bash
MUJOCO_GL=egl sim/.venv/bin/python analysis/render_simulation_sequence.py
python analysis/build_simulation_sequence.py
```

The task sequence follows the first fixed-start I0E3 trial at 0, 115, 150, 204, 281, and 296 s; task completion is at 310.042 s. A fixed external camera frames the robot, middle elevator, and panel, with close-up details for the final two frames. The records preserve original archive hashes, state indices, configurations, colors, and rendering settings.

## Audit behavior and timing

`analysis/audit_behavior.py` recomputes the staged arm-deployment counts and S3 LOOP diagnostics from [behavior-evidence.json](../results/behavior-evidence.json). This file contains API-event summaries, local-skill parameters and timing intervals, and a public tool-call sequence showing historical-image consultation during execution.

To regenerate the compact evidence from the original research archive:

```bash
python analysis/audit_behavior.py --archive /path/to/original/simulation/archive
```

The default audit uses the released files. Local LOOP execution intervals use the simulator task clock; overall local-trial times use the agent-start clock defined in the [methods](METHODS.md).

## Build the manuscript

Use Tectonic or a LaTeX installation with `pdflatex`, `bibtex`, Latin Modern, `natbib`, `booktabs`, `caption`, `geometry`, `microtype`, and `hyperref`.

```bash
bash paper/build.sh
```

The output is [paper/main.pdf](../paper/main.pdf). [arxiv-source.tar.gz](../paper/arxiv-source.tar.gz) contains the self-contained submission source, bibliography style, and figure PDFs. Its independent build reproduces the reviewed 23-page manuscript. References follow first-citation order, and the appendices begin on a new page after the bibliography. [The final manuscript audit](../results/final-manuscript-audit.json) records the numerical, citation, and layout checks.

## Set up the simulation

Install the pinned simulation dependencies in a separate environment:

```bash
python3 -m venv sim/.venv
sim/.venv/bin/python -m pip install -r sim/requirements-local.txt
PYTHON="$PWD/sim/.venv/bin/python" bash sim/run.sh scripts/check_runtime.py --seconds 5 --no-render
```

For a rendered initial-state preview:

```bash
PYTHON="$PWD/sim/.venv/bin/python" bash sim/run.sh scripts/preview_initial.py
```

Rendering normally uses EGL; `MUJOCO_GL=glfw` selects a graphical desktop display. The smoke test checks the simulator and API with scripted commands.

## Run new agent trials

The study launchers invoke a native coding-agent app server. New trials require a compatible installed runtime and access to the recorded model, `gpt-6-astra`, with reasoning setting `xhigh`. Use the corresponding launcher with a freshly prepared setup and a new output directory. Historical manifests preserve the original source paths and hashes; generate new manifests for a new installation.

The [input index](../experiments/README.md) identifies the source packages, task prompts, local states, and result files for each evaluation block.

## Check the hardware code offline

```bash
python -m pip install pytest numpy Pillow opencv-python pyserial
python -m pytest real/control_api/tests real/experiment/tests -q
```

These tests use fake transport and synthetic agents. For physical operation, create a named profile and an initial register backup for that robot, following the [commissioning workflow](REAL_ROBOT.md).

## Download the demonstration videos

The videos use Git LFS. After cloning the repository, retrieve them with:

```bash
git lfs install
git lfs pull
```

Both MP4s are silent. [The media manifest](../media/manifest.json) records durations, encoding, and checksums. The demonstration lasts 336.27 s; D3's task-event record gives a completion time of 360.036 s.
