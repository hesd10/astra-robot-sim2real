---
name: local-press
description: Execute one short base pulse near an already selected button and return fresh feedback.
---

Perform one bounded base pulse, stop, check health and return a fresh image set. You decide from the images whether another pulse is needed. No image-based decision occurs inside this function.

Run from the subject workspace: `python3 skill/local-press/scripts/run.py ' {"vx":0.04,"vy":0.0,"duration":0.8} '`. These example coordinates/directions are syntax examples, not a target location or a recommended movement for your current view. Supply your own parameters.

Translation speed norm <=0.06 m/s; duration 0.1..0.8s. The arm remains in its existing pose. No finish declaration occurs inside the helper. All images are current; supplied files must remain unchanged.
