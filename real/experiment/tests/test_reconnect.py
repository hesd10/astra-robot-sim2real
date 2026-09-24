import sys,json,io
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import gateway

def harness(monkeypatch,refusals,read_error=False):
 sockets=[];waits=[]
 class Socket:
  def __init__(self,*args):self.sent=[];sockets.append(self)
  def __enter__(self):return self
  def __exit__(self,*args):self.closed=True
  def settimeout(self,value):pass
  def connect(self,path):
   if len(sockets)<=refusals:raise ConnectionRefusedError(111,'Connection refused')
  def sendall(self,raw):self.sent.append(json.loads(raw))
  def makefile(self,*args):
   if read_error:raise ConnectionResetError('reply lost')
   return io.BytesIO(b'{"ok":true,"result":{"accepted":true}}\n')
 monkeypatch.setattr(gateway.socket,'socket',Socket);monkeypatch.setattr(gateway.time,'sleep',waits.append)
 return sockets,waits

def test_third_reconnect_succeeds_once(monkeypatch):
 sockets,waits=harness(monkeypatch,3)
 assert gateway.rpc('/unused','move',id='stable')['accepted']
 assert len(sockets)==4 and waits==[.5,1,1.5]
 assert [q for s in sockets for q in s.sent]==[{'op':'move','id':'stable'}]
 assert all(s.closed for s in sockets)

def test_exhausted_reconnects_send_nothing(monkeypatch):
 sockets,waits=harness(monkeypatch,10)
 with pytest.raises(ConnectionRefusedError):gateway.rpc('/unused','base')
 assert len(sockets)==4 and len(waits)==3 and not any(s.sent for s in sockets)

def test_reply_failure_does_not_replay_motion(monkeypatch):
 sockets,waits=harness(monkeypatch,0,True)
 with pytest.raises(ConnectionResetError):gateway.rpc('/unused','move')
 assert len(sockets)==1 and len(sockets[0].sent)==1 and waits==[]

def test_normal_connection_has_no_delay(monkeypatch):
 sockets,waits=harness(monkeypatch,0)
 assert gateway.rpc('/unused','state')['accepted']
 assert len(sockets)==1 and waits==[]
