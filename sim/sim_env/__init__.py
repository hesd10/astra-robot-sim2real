"""Private experiment infrastructure. Never expose this package to the subject."""
import os

# Set before MuJoCo is imported, including multiprocessing spawn imports.
os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('LP_NUM_THREADS', '2')
