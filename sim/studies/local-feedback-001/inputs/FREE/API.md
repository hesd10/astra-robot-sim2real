# Robot interface v1

`robot.py` is startup infrastructure, not a supplied controller. Use it from the
workspace root. `call(op, **fields)` returns a JSON-compatible result. Calls do not
wait for motions to finish. You may write your own programs using this module.

| Operation | Fields | Behavior |
|---|---|---|
| schema | none | Camera roles, joint limits/reference and command limits |
| state | none | Timestamped joint state, virtual health, motion status |
| observe | none | New synchronized head/left_wrist/right_wrist image set |
| move | targets: joint-to-radian dictionary; duration: seconds | Smooth bounded joint targets; rejected if too fast or another joint segment is active |
| base | vx, vy (m/s), wz (rad/s), duration (seconds) | Body-frame forward/left/CCW velocity, duration at most 1 second |
| stop | none | Cancel joint trajectory while retaining applied targets; ramp base to zero |
| finish | outcome: success, failure or contamination | End this attempt; cannot resume motion |

`python robot.py schema` and `python robot.py state` print state information.
`python robot.py observe` saves only the three onboard frames and their timestamps
under `evidence/` and prints paths. Python `observe(directory='evidence')` does the
same. Image files are JPEG. Observe captures after the request reaches the service,
then renders that one snapshot; it never substitutes an earlier cached image.
Physics keeps running while rendering. Request latency and frame age are returned.
Concurrent requests can share a snapshot only if they all preceded its capture.

Use `--json` for operation fields. Joint identifiers are left_1 through left_6,
right_1 through right_6, head_1 and head_2. Units are radians relative to the fixed
encoder reference. Startup positions are not definitions of zero. Read schema
for numeric bounds; no spatial endpoint interpretation is provided.

Base target speed is at most 0.10 m/s combined and 15 degrees/s yaw. Joint move
duration is at most 10 seconds. The trajectory uses smoothstep interpolation and
rejects insufficient duration. Commands update targets through finite-force
actuators; actual position can differ. Base velocity readback is the command,
not odometry. No global base position or orientation is supplied.

Every request carries an id. `call` generates one unless `request_id` is passed.
If a motion acknowledgement times out, retry the identical payload with the same
id to resolve it without executing twice. Reusing an id with different motion
fields is rejected. Observations are read-only and every call requests a fresh
capture. Do not use simultaneous callers unless their motion intent is compatible.

The virtual risk accumulator never decreases during an attempt. A fault disables
new motion and ends the attempt. There is no task-success, reset, camera-selection,
world-state or configuration-write operation. Your finish declaration is recorded
independently of private evaluation.

## Observation and head motion

Request observations as needed; there is no mandatory polling frequency. Each
observe call renders all three onboard cameras from one fresh capture; you may
inspect whichever returned views are useful. Camera left/right names denote the
robot's physical sides. Wrist cameras move with their arms, not independently.
The operator's third-person presentation camera is not available to the agent.

`head_1` is pan and `head_2` is tilt. Before moving the head, read and retain the
fresh initial `head_1` position outside skill/. Keep pan within that value ±π/2,
throughout the attempt. This is a task constraint; the service does not enforce
this relative restriction. Pan is a continuous joint: schema reports continuous
true and minimum/maximum null. Its angle is unwrapped, not reduced modulo 2π.
Command finite targets in the same unwrapped reference; velocity, acceleration
and torque limits still apply. Other joints retain their finite schema limits.
Tilt may use its full schema range (currently −0.76 to 1.45 radians). Head motion
uses the same bounded `move` operation as arm motion. Numeric encoder endpoints
for arm joints do not supply their spatial meaning.

## Timing, evidence and transfer

Physics continues during reasoning, programming and rendering. Inspect capture
times and frame age before relying on observations. Base commands expire without
refresh. `stop` retains applied joint targets; it does not return to a home pose.
Virtual health models experimental cost, not real motor temperature, voltage,
registers or lifetime. Never bypass, disable or reset limits or protection.

Use a fresh workspace/conversation. Read PRIOR.md for the authorized inputs.
Only the information, historical demonstrations and executable action skills explicitly listed in PRIOR.md may be used in addition to current-run observations. Numeric action templates in an authorized skill are permitted. Decide from current observations whether and how to use supplied material; a skill call completing does not establish task success. Keep supplied input files unchanged and write new code/evidence separately. All other model assets, scene internals, previous workspaces/conversations, external controllers and hidden evaluation remain unavailable. You may infer relationships and write controllers from authorized inputs and current observations. Stop safely on contamination.

There is no required exploration phase. All reading, programming, demonstration viewing, exploration and observations use the same task budget. Do not update or transfer experience onward. After finish, write a brief evidence report; closeout and video export are outside task time. The chassis frame is +X forward, +Y left, +Z up. No environmental geometry measurements are supplied. Historical observations are not current observations.

If historical media are supplied, MEDIA.md describes the common read-only viewing helper and timestamp convention. Every condition has the same helper. No live perception or control is performed by it.

Task completion requires physically activating the target button and observing
its red indicator in fresh images. Withdrawal, release and a two-second stable
stop are not success conditions. Choose arms and observation strategy freely.
Safe termination still uses stop and finish.
