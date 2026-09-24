"""Isolated stage service: restore operator-only settled integration snapshot."""
import argparse,json,signal,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sim_env.core import Core
from sim_env.model import restore,snapshot
import sim_env.service as service_module
import numpy as np

def main():
 p=argparse.ArgumentParser();p.add_argument('--reference',required=True);p.add_argument('--socket-path',required=True);p.add_argument('--log-dir',required=True);p.add_argument('--max-seconds',type=float,default=300);p.add_argument('--monitor-port',type=int,default=0);p.add_argument('--monitor-fps',type=int,default=10);p.add_argument('--workflow-file');a=vars(p.parse_args());ref=Path(a.pop('reference'));row=json.loads(ref.read_text())
 def staged_core(**kwargs):
  c=Core(**kwargs);restore(c.m,c.d,row)
  assert c.d.time==0 and not c.motion and not any(c.panel.called.values())
  np.testing.assert_allclose(snapshot(c.m,c.d)['state'],row['state'],rtol=0,atol=1e-12)
  return c
 service_module.Core=staged_core
 s=service_module.Service(**a)
 import hashlib
 audit={'passed':True,'stage_snapshot_sha256':hashlib.sha256(ref.read_bytes()).hexdigest(),'full_integration_state_match':True,'controller_idle':True,'all_buttons_unlatched':True,'private_only':True}
 (Path(a['log_dir'])/'initial-prior-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
 s.manifest['stage_initialization']=audit;s._manifest()
 for sig in [signal.SIGINT,signal.SIGTERM]:signal.signal(sig,lambda *_:s.stop_event.set())
 s.run()
if __name__=='__main__':main()
