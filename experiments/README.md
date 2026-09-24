# Inputs and evidence index

## Primary materials

| Study | Released material | Result rows |
|---|---|---|
| Fixed simulation start | [Condition inputs](../sim/studies/body-experience-001/inputs/) | [Fixed-start trials](../results/fixed-start.json) |
| Displaced simulation starts | [Positions and setup](../sim/studies/position-perturbation-001/) | [Paired trials](../results/perturbation.json) |
| Local skills | [Condition inputs](../sim/studies/local-feedback-001/inputs/) and [saved states](../sim/studies/local-feedback-001/states/) | [Skill trials](../results/local-skills.json) |
| Real robot | [Common prompt/API and condition materials](real/) | [Real trials](../results/real.json) |

Real condition B uses the simulation I3 body assets; real condition C uses the ordinary simulation E3 package. Both are in the [body/experience study](../sim/studies/body-experience-001/). Real condition D uses a distinct experience package extracted from the fastest no-assets/no-experience real trial. The common task prompt specifies the current scene and goal; historical materials supply references for the new task. [Methods](../docs/METHODS.md) defines all conditions.

## Programs and behavioral evidence

[final_advance.py](emergent-example/evidence/control/final_advance.py) is the original local visual-feedback program generated during a simulation trial. It uses that episode's helper modules. The reusable STEP/LOOP implementations are included in the [local-feedback study](../sim/studies/local-feedback-001/).

[Public motion-request records](../results/public-actions/) contain the real trials' normalized commands. [Geometry evidence](../results/geometry-evidence.json) and [behavior evidence](../results/behavior-evidence.json) identify the calculations, historical-image reads, staged arm deployment, and online adjustments discussed in the paper.

## Provenance

[Source notes](source-notes/) preserve the original experimental protocols. English descriptions appear in the [methods](../docs/METHODS.md) and [paper](../paper/main.pdf). Trial prompts, program strings, and source notes retain their recorded wording for traceability.

[The source manifest](source-manifest.json) records source-to-release paths and original SHA-256 hashes. [Release adjustments](release-adjustments.json) lists changes to make launchers portable. The repository provides per-trial metrics, public action records, selected states and images, and demonstration video; dense simulator streams and full onboard recordings remain in the research archive.
