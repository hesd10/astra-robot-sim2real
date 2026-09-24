# Real-robot implementation

The implementation includes calibration, coordinated control, three-camera recording, operator feedback, and pilot/formal experiment panels. The study uses a custom four-wheel mecanum XLeRobot.

The [operation guide](../docs/REAL_ROBOT.md) describes calibration, runtime parameters, panel controls, and end-of-use restoration. Configure a separate named profile for each physical robot and preserve its original register backup. The included numerical calibration is a fixture for fake-transport tests.

## Offline verification

From the repository root, with the dependencies in the [reproduction guide](../docs/REPRODUCING.md):

```bash
python -m pytest real/control_api/tests -q
python -m pytest real/experiment/tests -q
```

These checks use fake transport and synthetic agents. The [real-task materials](../experiments/real/) preserve the study's prompts and condition inputs; the [methods](../docs/METHODS.md) describe the executed success protocol.
