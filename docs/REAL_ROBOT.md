# Real-robot calibration and operation

The physical elevator-task stack provides calibration, coordinated joint and base control, three-camera feedback and recording, and operator panels for pilot and formal trials.

## Modules

- [Calibration](../real/calibration/): named profiles, register backups, joint signs/zeros/ranges, camera roles, wheel geometry, and direction checks.
- [Control API](../real/control_api/): coordinated motion, camera reads, recording, maintenance operations, and a supervised motor service.
- [Experiment panels](../real/experiment/): separate pilot and formal workflows, fresh trial workspaces, and proactive operator feedback.

Create a separate named profile for each physical robot. The included [calibration fixture](../real/calibration/sessions/real-001/calibration.json) supports offline tests; commissioning records the connected robot's own measurements and register backup.

## Commissioning workflow

1. Create the named profile and back up the initial motor registers before changing runtime parameters.
2. Identify each arm as a group, record approximate XML-reference zeros, and measure ranges by arm. Determine the positive direction of each joint separately. The reverse-mounted head reference uses pan `q = pi`.
3. Enter wheel diameter, track, and wheelbase. Establish wheel mapping and signs, then check forward, lateral, and yaw motion with short operator-supervised tests.
4. Identify head, left-wrist, and right-wrist cameras from their images and save the mapping. Camera geometry supplied as prior information remains the simulation reference.
5. Apply the intended speed/acceleration profile, read it back, and save a ready-for-experiment backup. Restore only the intended runtime fields when changing profiles.
6. Prepare the common arms/head task pose, place the base manually, and start the trial. The operator reports success, wrong-button, or stop events proactively.

The formal study uses a 0.10 m/s base translation cap. Base commands can run continuously for up to 5 s and accept velocity updates during motion; expiry and explicit stop requests stop the base. Motor temperature and tracking protection remain with the low-level firmware.

## Pilot and formal panels

Set `ASTRA_ROBOT_PROFILE` to the connected robot's named profile. Physical operation requires `scservo_sdk` and the serial/camera dependencies. From the repository root, the panel launchers are:

```bash
bash real/experiment/run-pilot.sh
bash real/experiment/run-formal.sh
```

Both default to demo mode; `--mode real` selects hardware operation. Pose preparation and trial start are separate panel actions. The formal workflow records outcomes, supports resuming between completed trials, and prepares the arms and head before each new trial's clock starts. The [methods](METHODS.md) define the experiment's operator-confirmed contact criterion.

The panels retain the Chinese field labels used during the study; this guide describes their workflow in English.

## End of use

Keep the ready-for-experiment parameters between trials. At the end of the entire experiment, explicitly restore the original runtime parameters and release torque. Complete wheel zero-speed writes before the final torque release, since those writes can re-enable torque on STS3250 motors.
