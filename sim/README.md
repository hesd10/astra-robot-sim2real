# Simulation implementation

The elevator task runtime combines MuJoCo simulation, robot and scene assets, a low-level control API, and agent-study launchers.

Install the pinned dependencies and run the API smoke check following the [reproduction guide](../docs/REPRODUCING.md). `scripts/check_runtime.py --seconds 5 --no-render` checks the simulator and API locally. New agent trials also require the model runtime described in that guide.

## Study materials

- [Body knowledge and experience](studies/body-experience-001/): information conditions, source experience, and fixed-start inputs.
- [Displaced starts](studies/position-perturbation-001/): positions and setup records for the paired comparisons.
- [Local feedback skills](studies/local-feedback-001/): saved near-button states and STEP/LOOP implementations.

Create a fresh setup and output directory for each new evaluation. Historical manifests identify the original experiment's source paths and hashes.

[Released results](../results/) contain the per-trial measurements used in the paper. [The evidence index](../experiments/README.md) links provenance records, and [the asset manifest](ASSET_MANIFEST.json) identifies robot meshes and scene assets.
