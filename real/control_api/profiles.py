"""Command trajectory limits copied from frozen simulation sim_env/core.py.
Feetech register 41 unit is 100 encoder steps/s²; source in verification/feetech-register-manual.pdf.
"""
import math

def joint_profile(name):
    degrees=20 if name.startswith('head') else 15 if name.endswith(('_4','_5')) else 10
    speed=math.radians(degrees)
    return dict(speed=speed,acceleration=3*speed,raw_velocity=math.ceil(speed*4096/(2*math.pi)),raw_acceleration=math.ceil(3*speed*4096/(2*math.pi*100)))
BASE_TRANSLATION_SPEED=.1
BASE_YAW_SPEED=math.pi/12
BASE_TRANSLATION_ACCELERATION=.2
BASE_YAW_ACCELERATION=math.pi/6

def base_raw_acceleration(calibration):
    matrix=calibration["base"]["solution"]["matrix_body_mps_radps_to_wheel_radps"]
    peak=max(math.hypot(*row[:2])*BASE_TRANSLATION_ACCELERATION+abs(row[2])*BASE_YAW_ACCELERATION for row in matrix)
    return math.ceil(peak*4096/(2*math.pi*100))
