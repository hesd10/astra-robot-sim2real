# Supplementary and exploratory comparisons

These studies examine written-experience iteration, initial target information, and experience representation. They provide context for the four main evaluation blocks in the [report](REPORT.md). Appendix C of the [paper](../paper/main.pdf) covers the exploratory studies; Appendix A gives the complete fixed-start results also summarized below.

## Earlier simulation text-experience iteration

An earlier six-episode simulation sequence accumulated written experience between sessions. The first five episodes succeeded in 18:37, 16:04, 14:14, 14:10 and 19:54; the sixth ended in declared failure at 27:36. Three-repeat evaluations of the input versions used in episodes four and five all succeeded, with means of 16:29 and 17:19, a small difference relative to trial variation. These mixed results motivated the controlled comparisons of experience representations in the main study.

## Complete fixed-start information matrix

| Body information | E0 | E1 | E2 | E3 |
|---|---:|---:|---:|---:|
| I0 | 1024.9 | 878.1 | 850.7 | 321.4 |
| I1 | 1160.4 | — | — | — |
| I2 | 579.8 | — | — | — |
| I3 | 437.1 | 541.7 | 499.8 | 288.9 |

Values are mean seconds, with three trials per tested cell; dashes denote untested cells. [Methods](../docs/METHODS.md) defines the information and experience levels. E3 has the clearest repeated advantage. At I0, the E1/E2 difference is 27.4 s, small relative to E2 variation; at I3, both are slower than E0. The synchronized representation combines images, actions, and states into a useful reference for execution.

## Exploratory initial target pose

One trial per condition yielded 11:15 with neither body assets nor an initial target pose, 7:10 with body assets, 15:21 with an initial target pose, and 5:26 with both. All four trials succeeded. The combined condition was fastest in this exploratory comparison; body geometry and current images can also support relative localization during execution.

## Compact experience and expanded reflection

The comparison uses ordinary E3, a compact experience package, and an expanded reflection guide at six test points.

| Measurement | Ordinary E3 | Compact experience | Expanded reflection |
|---|---:|---:|---:|
| First (historical E3 reference) | 370.35 s | 384.53 s | 404.30 s |
| Second (interleaved new trials) | 354.47 s | 325.63 s | 413.67 s |

The first measurement reuses six historical E3 trials and adds 12 compact/reflection trials. The second adds 18 interleaved trials, six per condition at the same six points. All new trials succeeded. Times use the agent execution clock, from its first turn to accepted task completion.

Compact experience is faster than expanded reflection in 10/12 pointwise comparisons, and faster than ordinary E3 at 3/6 points in each measurement. The packages change both content and organization, including selected images and reading cost; ordinary E3 already includes qualitative guidance. This comparison therefore examines the practical effect of different experience packages.

A compact-experience trial in the first measurement also supplies the spontaneous local feedback routine later evaluated as STEP and LOOP. The [original program](../experiments/emergent-example/evidence/control/final_advance.py) and [skill results](REPORT.md#3-emergent-local-program-and-skill-evaluation) connect that observation to the controlled reuse study.
