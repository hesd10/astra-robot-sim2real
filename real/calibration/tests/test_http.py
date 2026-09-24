import sys,json,threading,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from controller import Controller
from server import Server

@pytest.fixture
def api(tmp_path):
    c=Controller(tmp_path,demo=True);s=Server(('127.0.0.1',0),c)
    t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
    yield s,c
    s.shutdown();s.server_close();c.disconnect()

def request(s,path,payload=None,token=True,origin=None):
    headers={}
    if token:headers['X-Calib-Token']=s.token
    if origin:headers['Origin']=origin
    data=None if payload is None else json.dumps(payload).encode()
    if data:headers['Content-Type']='application/json'
    req=urllib.request.Request(f'http://127.0.0.1:{s.server_port}'+path,data=data,headers=headers)
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5)

def test_no_csrf_or_wrong_origin_cannot_connect(api):
    s,c=api
    for token,origin in [(False,None),(True,'https://other.invalid')]:
        with pytest.raises(urllib.error.HTTPError) as e:request(s,'/api/action/connect',{},token,origin)
        assert e.value.code==403 and not c.connected

def test_valid_api_connect_export_no_motion_route(api):
    s,c=api
    assert json.load(request(s,'/api/action/connect',{}))['connected']
    with pytest.raises(urllib.error.HTTPError) as e:request(s,'/api/action/move',{'targets':{}})
    assert e.value.code==400
    response=request(s,'/api/export');assert response.headers['Content-Type']=='application/zip'
    assert response.read()[:2]==b'PK'
    assert json.load(request(s,'/api/action/disconnect',{}))['connected'] is False

def test_camera_import_cannot_escape_workspace(api):
    s,c=api
    with pytest.raises(urllib.error.HTTPError):request(s,'/api/camera_import',{'files':[{'name':'../oops.json','data':'e30='}]})
    assert not (c.ws.parent/'oops.json').exists()

def test_named_profile_http_switch_is_offline_and_preserves_data(tmp_path):
 from registry import Registry
 from workflow import Workflow
 r=Registry(tmp_path/'robots',demo=True);r.create('Beijing');w=Workflow(r,Controller);c=w.load('Beijing');s=Server(('127.0.0.1',0),c,w);threading.Thread(target=s.serve_forever,daemon=True).start()
 try:
  d=json.load(request(s,'/api/machine/create',{'name':'Shanghai'}));assert d['machines']['selected']=='Shanghai' and not d['connected']
  d=json.load(request(s,'/api/machine/load',{'name':'Beijing'}));assert d['machines']['selected']=='Beijing' and not d['connected']
  with pytest.raises(urllib.error.HTTPError):request(s,'/api/machine/apply',{})
  assert not w.controller.connected and w.process is None
 finally:s.shutdown();s.server_close();w.controller.running=False;w.controller.disconnect()
