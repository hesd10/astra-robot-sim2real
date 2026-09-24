---
name: local-press
description: Execute a local visual feedback press near an already selected and aligned button, stopping on red indication.
---

Perform repeated bounded base pulses, observing after each and stopping when red pixels appear in the target ROI or the budget is exhausted. Choose the target ROI and motion direction from fresh images before calling. This is a fixed-ROI color check, not target recognition or alignment control. A red_detected_verify result is provisional: inspect the returned image before declaring success. If alignment changes, the target leaves the ROI, or progress fails, stop using this helper and reassess.

Run from the subject workspace: `python3 skill/local-press/scripts/run.py ' {"vx":0.04,"vy":0.0,"duration":0.8,"regions":{"head":[400,250,570,410]},"max_steps":6,"max_seconds":30} '`. These example coordinates/directions are syntax examples, not a target location or a recommended movement for your current view. Supply your own parameters.

Translation speed norm <=0.06 m/s; duration 0.1..0.8s. The arm remains in its existing pose. No finish declaration occurs inside the helper. All images are current; supplied files must remain unchanged.
