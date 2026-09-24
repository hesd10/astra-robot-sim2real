# Demonstration media

## Real-robot demonstration

The D3 trial reuses real experience from a new starting position. The videos show the full supplied external recording:

| Video | Speed | Duration | Audio |
|---|---|---:|---|
| [D3-realtime-muted.mp4](D3-realtime-muted.mp4) | Original | 336.27 s | None |
| [D3-6x-muted.mp4](D3-6x-muted.mp4) | 6× | 56.03 s | None |

Both are H.264, portrait 1080×1920, 30 fps, with HDR converted to BT.709 SDR for broad playback compatibility. Both outputs were fully decoded and checked for absence of an audio stream. The task event log records a completion interval of 360.036 s.

The illustrative frames show the [start](D3-start.jpg), [approach](D3-approach.jpg), and [near-button view](D3-near-button.jpg) at video times 0, 150, and 315 s. These are external operator views.

Videos use Git LFS. Run `git lfs install` and `git lfs pull` after cloning to download them. [manifest.json](manifest.json) records checksums and encoding properties.

## Simulation setup

[simulation-lobby-start.png](simulation-lobby-start.png) and [simulation-target-panel.png](simulation-target-panel.png) are MuJoCo renders of the saved original starting state. The overview uses an external cutaway camera, with the near wall hidden for rendering. The panel image shows the middle elevator's UP/DOWN buttons. [The rendering script](../analysis/render_simulation_scene.py) reproduces both views, and [scene provenance](../results/simulation-scene-provenance.json) records source hashes, camera settings, and image checksums. [The figure builder](../analysis/build_scene_figure.py) adds the paper's labels and arrows.

## Recorded arm-pose comparison

The [initial](arm-pose-initial.png), [source](arm-pose-source.png), and [reused](arm-pose-reuse.png) arm poses show recorded configurations at 0 s and 481 s in source trial `be001-source-3`, and 141 s in the first no-assets/E3 trial `be001-r1-i0e3`. A common robot-relative camera angle makes the configurations comparable. [Snapshot records](../results/arm-pose-snapshots.json) contain the saved configurations, archive hashes, and record indices. [The renderer](../analysis/render_arm_poses.py) displays these saved states; [the figure builder](../analysis/build_arm_pose_figure.py) assembles the comparison.

## Recorded task sequence

The [six-frame sequence](../paper/figures/simulation-sequence.png) follows the first no-assets/E3 simulation trial from its start through arm deployment, approach, alignment, and button activation. Frames use recorded states at 0, 115, 150, 204, 281, and 296 s, with two detail views of final alignment and activation. The task finishes at 310.042 s.

[Snapshots](../results/simulation-sequence-snapshots.json) and [render provenance](../results/simulation-sequence-provenance.json) identify the source states and camera. [The renderer](../analysis/render_simulation_sequence.py) creates the individual frames, and [the figure builder](../analysis/build_simulation_sequence.py) assembles the paper figure. See the [reproduction guide](../docs/REPRODUCING.md) for commands.
