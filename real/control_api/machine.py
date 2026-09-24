from pathlib import Path
import json,os
ROOT=Path(__file__).resolve().parents[1]
def paths(profile=None):
 selected=profile or os.environ.get('ASTRA_ROBOT_PROFILE')
 if not selected:return dict(name='Beijing',backup=ROOT/'register-backups/20260922-094516-before-calibration',calibration=ROOT/'calibration/sessions/real-001/calibration.json',cameras=ROOT/'control_api/camera-config.json',pose=ROOT/'control/elevator-task-initial-pose.json')
 p=Path(selected).resolve();meta=json.loads((p/'profile.json').read_text());backup=meta.get('initial_backup')
 if not backup:raise ValueError('Selected robot has no initial backup')
 return dict(name=meta['name'],backup=Path(backup),calibration=p/'calibration/calibration.json',cameras=p/'camera-config.json',pose=p/'task-pose.json')
