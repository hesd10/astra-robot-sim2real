"""Geometry/material checks plus real no-inference launch fixture."""
import json,uuid
from body_experience_study import STUDY,ROOT,validate
from prior_materials import write_json

def main():
    import mujoco,numpy as np
    validate()
    a=mujoco.MjModel.from_xml_path(str(STUDY/'body/I2/robot/robot.xml'));b=mujoco.MjModel.from_xml_path(str(STUDY/'body/I3/robot/robot.xml'))
    assert a.ncam==0 and b.ncam==3
    for k in ['body_pos','body_quat','jnt_pos','jnt_axis','geom_pos','geom_quat','geom_size','mesh_vert']:
        np.testing.assert_array_equal(getattr(a,k),getattr(b,k))
    assert (STUDY/'inputs/I0E0/robot.py').read_bytes()==(ROOT/'subject_template/robot.py').read_bytes()
    import check_prior_launch as test
    import start_prior_experiment as launcher
    launcher.run_agent=test.fixture
    run=launcher.start('verification-body-'+uuid.uuid4().hex[:8],input_dir=STUDY/'inputs/I0E0',reference=STUDY/'private-initial-reference.json',setup=ROOT/'setups/formal-001.json',max_seconds=60.)
    r=json.loads((run/'private/simulation/result.json').read_text());assert r['actions']==0 and r['fault'] is None
    assert all((run/'private'/f).stat().st_size>0 for f in ['dashboard.mp4','follow.mp4','follow-compact.mp4'])
    write_json(STUDY/'VALIDATION.json',{'passed':True,'mechanical_arrays_exactly_equal_I2_I3':True,'I2_cameras':0,'I3_cameras':3,'common_files_identical':True,'real_simulation_and_video_fixture':str(run),'model_calls':0,'earlier_fixture_issue':'stdin multiprocessing spawn; corrected by executable file with main guard; no subject model was called'})
    print('PASS body geometry, input integrity and real simulation/video integration')

if __name__=='__main__':main()
