"""Restricted device transport: reads + explicit torque release only."""
from pathlib import Path
import fcntl
import json
import hashlib
import time
from domain import signed_magnitude

class Hardware:
    def __init__(self, backup, audit):
        self.backup = Path(backup); self.audit = audit
        self.ports = {}; self.locks = []; self.motors = {}; self.packet = None
    def read(self, key, address, length):
        m = self.motors[key]
        data, comm, err = self.packet.readTxRx(self.ports[m['serial']], m['id'], address, length)
        if comm != 0 or err or len(data) != length:
            raise RuntimeError(f"{m['short']} 读取失败：通信 {comm}，电机 {err}")
        return list(data)
    def connect(self):
        import scservo_sdk as scs
        hashes = json.loads((self.backup/'SHA256SUMS.json').read_text())
        for name, sha in hashes.items():
            p = (self.backup/name).resolve()
            if not p.is_relative_to(self.backup.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
                raise RuntimeError('寄存器备份校验失败')
        report = json.loads((self.backup/'REPORT.json').read_text())
        if not report['all_complete']: raise RuntimeError('备份不完整')
        self.packet = scs.PacketHandler(0)
        try:
            for m in report['motors']:
                serial = m['usb_serial_path']; sid = m['id']; key = f'{serial}:{sid}'
                if serial not in self.ports:
                    lock = open('/tmp/passive-calibration-'+serial+'.lock', 'a')
                    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except Exception: lock.close(); raise RuntimeError('串口正在被另一个标定进程使用')
                    self.locks.append(lock)
                    port = scs.PortHandler('/dev/serial/by-id/'+serial)
                    if not port.openPort(): raise RuntimeError('无法打开串口 '+serial)
                    self.ports[serial] = port
                    # OS-level exclusivity for cooperating serial users, without setting servo registers.
                    port.ser.exclusive = True
                original = json.loads((self.backup/m['folder']/'pass-1.json').read_text())
                self.motors[key] = dict(serial=serial, id=sid, short=f"{serial.split('_')[-1].split('-')[0]} · ID {sid}", model=m['model_candidates'][0], original=original)
                config = self.read(key, 0, 40)
                if config != original[:40]: raise RuntimeError(f"{self.motors[key]['short']} 配置与备份不同，请先核对，未进行任何写入")
            return self.sample()
        except BaseException:
            self.close(); raise
    def sample(self):
        result = {}
        for key, m in self.motors.items():
            pos=self.read(key,56,4);torque=self.read(key,40,1)[0]
            result[key]=dict(present_raw=pos[0]|pos[1]<<8,present=signed_magnitude(pos[0]|pos[1]<<8),torque=torque,velocity_raw=pos[2]|pos[3]<<8,stamp=time.time())
        return result
    def check_configs(self):
        for key,m in self.motors.items():
            if self.read(key, 0, 40) != m['original'][:40]:
                raise RuntimeError(f"{m['short']} 配置在采集中变化；停止采集，请核对")
    def release(self, keys):
        if not keys or len(keys) != len(set(keys)) or any(k not in self.motors for k in keys):
            raise ValueError('请选择有效且不重复的电机')
        self.check_configs()
        result = []
        for key in keys:
            m=self.motors[key]
            before=self.read(key,40,1)[0]
            event=dict(kind='torque_release_intent', motor=key, address=40, old=before, new=0)
            self.audit(event)  # Durable log before any write.
            # The only hardware WRITE allowed by this application. No generic write endpoint.
            comm,err=self.packet.write1ByteTxRx(self.ports[m['serial']],m['id'],40,0)
            after=self.read(key,40,1)[0]
            self.audit(dict(kind='torque_release_result',motor=key,comm=comm,error=err,readback=after))
            if comm != 0 or err or after != 0:
                raise RuntimeError(f"{m['short']} 释放未确认，已处理电机保持现状，请检查")
            result.append(key)
        return result
    def close(self):
        # Never enable torque or replay targets on disconnect.
        for port in self.ports.values():
            try: port.closePort()
            except Exception: pass
        for lock in self.locks: lock.close()
        self.ports={}; self.locks=[]; self.motors={}
