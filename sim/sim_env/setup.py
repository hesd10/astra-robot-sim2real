"""Operator-only starting-pose definitions, kept outside the subject workspace."""
import hashlib
import json
import math
from pathlib import Path


def load_setup(path):
    path = Path(path).resolve()
    content = path.read_bytes()
    definition = json.loads(content)
    if not isinstance(definition, dict) or set(definition) != {'name', 'description', 'initialization'}:
        raise ValueError('setup requires name, description and initialization')
    if not isinstance(definition['name'], str) or not isinstance(definition['description'], str):
        raise ValueError('setup name and description must be text')
    initial = definition['initialization']
    if not isinstance(initial, dict) or set(initial) != {'standoff_m', 'lateral_m', 'yaw_deg'}:
        raise ValueError('setup initialization requires standoff_m, lateral_m and yaw_deg')
    for value in initial.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('setup coordinates must be finite numbers')
    if initial['standoff_m'] <= 0:
        raise ValueError('standoff must be positive')
    # Same conversion is used by the preview and the real experiment launcher.
    parameters = {'standoff': float(initial['standoff_m']), 'lateral': float(initial['lateral_m']),
                  'yaw': math.radians(initial['yaw_deg'])}
    return {'definition': definition, 'parameters': parameters,
            'source_path': str(path), 'sha256': hashlib.sha256(content).hexdigest()}
