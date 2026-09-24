# Real robot interface

Use `from robot import call, observe` in this workspace; CLI `python robot.py OP --json '{...}'` is equivalent. No built-in task controller or IK is supplied. Read `schema` for current limits. Angles are calibrated XML-reference radians, not relative to startup. Names left_1..6, right_1..6 denote physical sides. head_1 is pan, head_2 tilt. No spatial interpretation of arm channels is supplied.

|Operation|Fields|Meaning|
|---|---|---|
|schema|none|Joint bounds, target speed/acceleration and base limits|
|state|none|Timestamped joint positions, targets, motion_active, fault and operator event state|
|observe|none|Fresh head/left_wrist/right_wrist images; `observe()` saves JPEGs and returns paths|
|move|targets dictionary, duration seconds|Coordinated smoothstep segment, maximum 10 seconds; returns immediately|
|base|vx, vy, wz, duration|Body forward/left m/s, CCW rad/s; maximum 5 seconds of continuous velocity output, then decelerates to zero; an early update replaces the target without a forced stop|
|stop|none|Cancel joint trajectory, retain applied targets, command zero wheel speed|
|wait_feedback|timeout, 0..5 seconds|Optional stop and bounded event check; does not lock motion or require operator confirmation|
|events|none|Persistent operator events and waiting/terminal state|
|ack_events|event_ids list|Explicit acknowledgement that the model has read these events|
|finish|outcome: success/failure/contamination|End attempt and stop; success requires operator confirmation|

Joint target limits: shoulders/elbows/grippers 10°/s, 30°/s²; wrists 15°/s,45°/s²; head 20°/s,60°/s². Move durations must satisfy smoothstep peak speed and acceleration; calls return before physical execution finishes. Base maximum combined translation 0.10 m/s, yaw 15°/s, acceleration 0.20 m/s² and 30°/s². Actual movement may differ from the command. Base state is not measured body odometry; no global pose is supplied. Head pan is limited to its initial angle ±90° intersected with the real joint limits. Finite real ranges supersede historical simulation ranges.

Three USB cameras are independently captured, not synchronized. Wrist cameras move with their arms. Images include individual acquisition timestamps. No operator or external camera is provided. Firmware handles motor protection; the interface has no virtual health accumulator, temperature sampling or tracking-error gate. Communication/enable faults end motion availability. There is no reset or configuration-write operation.

The operator monitors continuously and proactively reports success. Success requires physically depressing the target button; visual overlap or initial contact alone is insufficient. Unless success is reported, treat the press as unsuccessful and continue adjusting without requesting confirmation. `wait_feedback` is optional and does not latch a motion block. Explicit failure/uncertain events, if sent, carry the current action ID but do not require acknowledgement before continuing. Success, wrong_button and stop immediately stop and lock all later motion independently of model delivery. Acknowledge received event IDs with `ack_events`; then finish and report. A lit indicator alone is not success; pressing an already-lit target remains required. Waiting and operator feedback latency count toward the 1800-second budget.

Every request has an ID; `call` generates one or accepts request_id. Retry uncertain motion acknowledgements with identical payload and ID only. A new ID is a new action. Do not resume an ended attempt. Use observations and current events over historical material. Save the brief final report in evidence/; do not create a transferable skill.
