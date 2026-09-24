import json,sys
from pathlib import Path
p=Path('prior/experience/observations/index.json')
if not p.exists():
 print('No historical media supplied.')
else:
 rows=json.loads(p.read_text())
 for row in ([rows[int(sys.argv[1])]] if len(sys.argv)>1 else rows):
  print(json.dumps(row))
