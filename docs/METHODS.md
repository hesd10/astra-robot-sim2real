# Experimental methods

The study evaluates body knowledge, successful experience, and reusable local programs in an elevator-button task. GPT-6-Astra uses current head and wrist images, joint feedback, and a common low-level control API. Each trial starts in a fresh session with a fixed set of supplied materials. The recorded model identifier is `gpt-6-astra`, with reasoning setting `xhigh`.

## Information and experience conditions

| Level | Supplied material |
|---|---|
| I0 | Common control API, actuator names, units, usable limits, and current feedback |
| I1 | I0 plus a qualitative description of the robot's structure |
| I2 | I1 plus mechanical XML, meshes, and joint mapping |
| I3 | I2 plus camera geometry and calibration |
| E0 | No historical experience |
| E1 | Astra-generated written summary of a successful source episode |
| E2 | E1 plus sampled images from three onboard cameras and their visualization |
| E3 | E2 plus synchronized action commands, robot states, and feedback |

A combined label such as I0E3 specifies both resource levels. The ten fixed-start conditions compare I0–I3 at E0, then E1–E3 at I0 and I3. The shared I0E0 and I3E0 baselines give four body-information conditions and six experience conditions, with three trials each.

All simulation experience representations derive from the fastest successful episode among three source runs at the original start: `be001-source-3` (638.352 s). Astra generates the written summary from its own execution, closing the loop from acting to summarizing and reusing experience. E2 and E3 contain three views at 22 sampled times, with each image held until the next sample in a visualization. The source package is fixed for the subsequent comparisons.

| Real condition | Supplied material |
|---|---|
| A | Common interface, with no extra body assets or experience |
| B | A plus simulation body assets corresponding to I3 |
| C | A plus the ordinary simulation E3 package |
| D | A plus real-robot E3 from the fastest A trial |

The real experience package contains an Astra-generated summary, 25 image triplets, and synchronized action/state records. [The input index](../experiments/README.md) links the released packages and their provenance.

## Tasks and robot setup

Simulation targets the middle elevator's UP button. Success requires target activation, a correct success declaration supported by fresh observations, no wrong-button event, and no recorded task fault. The red indicator supplies visual feedback; evaluator-side events support outcome checks.

The real lobby has two elevators on each side. The target is the DOWN call button between the two elevators opposite the initial robot position. Because the physical button is stiff and its light is unreliable, the executed success criterion is operator-confirmed gripper-tip contact with the target button. The preserved task prompt requests physical depression; Appendix D.3 of the paper records this difference. The operator reports success proactively, and Astra continues adjusting until that report arrives.

Both platforms have two six-channel arms, a pan–tilt head, and three cameras. We modified XLeRobot to use a four-wheel mecanum base. Hardware calibration maps joint offsets, signs, and ranges to the simulation convention; wheel geometry and motion directions are checked, and camera roles are confirmed from images. Camera geometry supplied as prior information comes from simulation. The agent locates the real target from current images. Arms and head are placed in the common task pose before timing starts; an operator places the base and starts each trial.

The APIs use joint angles in the fixed XML reference and base velocities in the robot's current frame. Both cap translation at 0.10 m/s and yaw at 15 degrees/s. Joint segments last at most 10 s. Simulation base commands last at most 1 s; real base commands allow up to 5 s of continuous output, with velocity updates during motion. A command's expiry or an explicit stop ends base motion.

## Local-skill conditions

| Condition | Available routine |
|---|---|
| FREE | Standard API and freedom to write control programs |
| STEP | One bounded base movement, feedback checks, and a fresh observation |
| LOOP | Repeated STEP movements with a red-pixel stopping check after each pulse |

Astra selects direction, speed, and duration; for LOOP it also selects an image region and execution budget. Both supplied routines cap translation at 0.06 m/s and pulse duration at 0.1–0.8 s. Astra confirms the final outcome.

The routine-discovery episode and evaluation-state episode are distinct. S1–S3 restore the same recorded arm pose with base offsets of 0, 2, and 4 cm backward from a near-button snapshot. Each state and condition is tested three times, with a 300 s task budget. Full approach tasks use a 1800 s budget.

## Timing and counts

| Evaluation | Start clock | End event |
|---|---|---|
| Fixed-start and displaced-start simulation | Simulation service task clock, including time between actions | Accepted success declaration |
| Local skills | First agent turn | Accepted success declaration |
| Real robot | First formal agent request after pose preparation | Accepted operator success report |
| Supplementary compression/reflection comparison | First agent turn | Accepted task completion |

Task time includes material reading, observation, model and service waiting, code generation, action execution, and outcome confirmation. Preparation, returning the robot to its start, and post-task export are excluded. Percentage reductions use the corresponding baseline within each evaluation block.

Motion counts are API requests: coordinated targets for several joints count as one request. Results provide means and individual trial times, with sample standard deviations in the supplementary tables. The [behavior audit](../analysis/audit_behavior.py) separately measures local execution spans and the intervals between skill calls.

## Trial schedule and starting positions

| Evaluation | Schedule and placement |
|---|---|
| Fixed start | 12 E0 trials, then nine I0 experience trials and nine I3 experience trials |
| Displaced starts | E0/E3 pairs at nine points: three directions at each 10, 50, and 100 cm radius; directions sampled separately for each radius, with initial heading and arm pose fixed |
| Local skills | Three states × three conditions × three repetitions, with condition order rotated |
| Real robot | ABC, BCA, CAB at a shared nominal start; D follows source selection, with D1 at that start and D2/D3 at two new starts |

The real base is placed manually. D2/D3 positions are recorded qualitatively; coordinates and headings were not surveyed. D's pooled mean summarizes its three placements.

## Behavioral evidence

XML parsing, coordinate transforms, forward-kinematics programs, and mesh inspection show how geometry is used. Historical file/image reads and subsequent action requests document experience use during deployment and approach. The [report](../report/REPORT.md) connects these records to the results and collects the study's limitations in one section.
