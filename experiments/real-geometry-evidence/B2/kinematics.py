import xml.etree.ElementTree as E
import numpy as np,json
root=E.parse('prior/body/robot/robot.xml').getroot()
mapping=json.load(open('prior/body/robot/interface_mapping.json'))['joint_channels_to_xml_joint_names']
def quat(s):
 w,x,y,z=np.fromstring(s,sep=' ');n=(w*w+x*x+y*y+z*z)**.5;w,x,y,z=np.array([w,x,y,z])/n
 return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
def fk(q):
 joints={mapping.get(k,k):v for k,v in q.items()};out={}
 def rec(e,P):
  T=np.eye(4);T[:3,:3]=quat(e.get('quat','1 0 0 0'));T[:3,3]=np.fromstring(e.get('pos','0 0 0'),sep=' ');T=P@T
  for j in e.findall('joint'):
   a=np.fromstring(j.get('axis','0 0 1'),sep=' ');a=a/np.linalg.norm(a);v=joints.get(j.get('name'),0);K=np.array([[0,-a[2],a[1]],[a[2],0,-a[0]],[-a[1],a[0],0]]);R=np.eye(3)+np.sin(v)*K+(1-np.cos(v))*K@K
   U=np.eye(4);U[:3,:3]=R;T=T@U
  out[e.get('name')]=T
  for c in e.findall('body'):
   if 'roller' not in c.get('name',''):rec(c,T)
 rec(root.find('worldbody/body'),np.eye(4));return out
if __name__=='__main__':
 q={'right_1':-np.pi/2,'right_2':np.pi,'right_3':np.pi/2,'right_4':np.pi/2,'right_5':np.pi/2}
 for k,t in fk(q).items():
  if k in ['Rotation_Pitch','Upper_Arm','Lower_Arm','Wrist_Pitch_Roll','Fixed_Jaw']:print(k,t.round(3))
 for b in root.iter('body'):
  if b.get('name') in ['Fixed_Jaw','Moving_Jaw']:
   print(b.get('name'),[g.attrib for g in b.findall('geom')])
