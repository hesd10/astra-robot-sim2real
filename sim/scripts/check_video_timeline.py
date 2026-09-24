"""Deterministic cut checks: idle wait removed, concurrent motion preserved."""
import json
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_env.video_timeline import model_waits,cut_plan


def main():
    fps=20
    frames=[{'frame':i,'sim_time':i/fps,'sample_monotonic':100+i/fps,
             'moving':5<=i/fps<6,'visual_change':i==140} for i in range(240)]
    rows=[{'event':'turn/requested','monotonic':101},
          {'event':'item/started','item_type':'commandExecution','item_id':'tool','monotonic':109},
          {'event':'item/completed','item_type':'commandExecution','item_id':'tool','monotonic':110},
          {'event':'turn/completed','monotonic':111}]
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'agent-timing.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        waits=model_waits(path)
    assert waits==[(101,109),(110,111)],waits
    keep=cut_plan(frames,waits,fps)
    assert not keep[50]                         # Long stationary wait.
    assert all(keep[100:120])                  # Motion while Astra thinks.
    assert all(keep[133:148])                  # Button/light change + buffer.
    assert all(keep[180:200])                  # Tool execution, not model wait.
    assert all(keep[:20]) and all(keep[-20:])  # Readable opening and ending.
    assert cut_plan(frames,[],fps).all()       # No invented cuts without timing.
    assert cut_plan(frames,[(100,100.5)],fps).all() # No tiny jump cuts.
    report={'passed':True,'concurrent_motion_preserved':True,'visual_changes_preserved':True,
            'tool_time_preserved':True,'idle_model_wait_removed':True,
            'frames':len(frames),'kept_frames':int(keep.sum())}
    (ROOT/'reports/local/video-timeline-check.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__=='__main__':main()
