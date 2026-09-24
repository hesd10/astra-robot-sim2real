"""Read-only named register snapshots. No temperature feedback or write instructions."""
import json,hashlib,shutil,fcntl,time
from pathlib import Path
from registry import write,read

def seal(folder):
 hashes={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='SHA256SUMS.json'}
 write(folder/'SHA256SUMS.json',hashes);archive=Path(shutil.make_archive(str(folder),'zip',root_dir=folder.parent,base_dir=folder.name))
 return dict(path=str(folder),archive=str(archive),sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
def capture(folder,name,serials,expected=None):
 import scservo_sdk as sdk
 folder=Path(folder);folder.mkdir(parents=True,exist_ok=False);report=dict(robot_name=name,instructions_used=['READ'],excluded_addresses={'63':'temperature feedback'},motors=[],all_complete=False)
 for serial in serials:
  if Path(serial).name!=serial or not (Path('/dev/serial/by-id')/serial).exists():raise ValueError('请选择当前存在的串口')
  with open('/tmp/passive-calibration-'+serial+'.lock','a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);port=sdk.PortHandler('/dev/serial/by-id/'+serial);packet=sdk.PacketHandler(0)
   if not port.openPort():raise RuntimeError('无法打开串口')
   port.ser.exclusive=True
   try:
    port.setBaudRate(1000000)
    ids=[m['id'] for m in expected['motors'] if m['usb_serial_path']==serial] if expected else range(1,21)
    for sid in ids:
     model,comm,err=packet.readTxRx(port,sid,3,2)
     if comm or err:
      if expected:raise RuntimeError(f'缺少已绑定电机 {serial}:{sid}')
      continue
     number=int.from_bytes(bytes(model),'little');models={777:'sts3215',2825:'sts3250'}
     if number not in models:raise ValueError(f'未支持的型号 {number}，需核对型号表后继续')
     dest=folder/serial/f'id-{sid:02d}';dest.mkdir(parents=True);passes=[]
     for index in (1,2):
      values=[None]*87
      for start,end in ((0,63),(64,87)):
       for addr in range(start,end,16):
        length=min(16,end-addr);v,c,e=packet.readTxRx(port,sid,addr,length)
        if c or e or len(v)!=length:raise RuntimeError(f'读取失败 {serial}:{sid}@{addr}')
        values[addr:addr+length]=v
      write(dest/f'pass-{index}.json',values);passes.append(values)
     a,b=passes
     if any(a[i]!=b[i] for i in list(range(56))+list(range(80,87))):raise RuntimeError('配置在备份期间变化，未封存')
     report['motors'].append(dict(usb_serial_path=serial,id=sid,model_number_raw=number,model_candidates=[models[number]],folder=str(dest.relative_to(folder)),configuration_same_twice=True))
   finally:port.closePort()
 if len(report['motors'])!=18:raise ValueError(f"发现{len(report['motors'])}电机，当前流程要求14关节+4轮共18个；原始读取已保留，未绑定")
 if expected:
  known={(m['usb_serial_path'],m['id']):m['model_number_raw'] for m in expected['motors']}
  if any(known.get((m['usb_serial_path'],m['id']))!=m['model_number_raw'] for m in report['motors']):raise ValueError('机器身份与初始备份不一致')
 report.update(all_complete=True,created_unix=time.time(),scan_ids=[1,20] if not expected else 'bound inventory');write(folder/'REPORT.json',report)
 return report
