import xml.etree.ElementTree as E
import numpy as np,json
root=E.parse('prior/body/robot/robot.xml').getroot()
mp=json.load(open('prior/body/robot/interface_mapping.json'))['joint_channels_to_xml_joint_names']
def quat(s):
 w,x,y,z=np.fromstring(s,sep=' ');n=np.linalg.norm([w,x,y,z]);w,x,y,z=np.array([w,x,y,z])/n
 return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
def axisrot(a,q):
 a=np.array(a);a=a/np.linalg.norm(a);x,y,z=a;K=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
 return np.eye(3)+np.sin(q)*K+(1-np.cos(q))*(K@K)
def fk(channels):
 angles={mp[k]:v for k,v in channels.items()};out={}
 def walk(el,T):
  for b in el.findall('body'):
   B=np.eye(4);B[:3,:3]=quat(b.get('quat','1 0 0 0'));B[:3,3]=np.fromstring(b.get('pos','0 0 0'),sep=' ')
   j=b.find('joint')
   if j is not None:
    R=np.eye(4);R[:3,:3]=axisrot(np.fromstring(j.get('axis','0 0 1'),sep=' '),angles.get(j.get('name'),0));B=B@R
   U=T@B;out[b.get('name')]=U;walk(b,U)
 walk(root.find('worldbody'),np.eye(4));return out
if __name__=='__main__':
 q={'right_1':-np.pi/2,'right_2':np.pi,'right_3':np.pi/2,'right_4':np.pi/2,'right_5':np.pi/2}
 for p in [3.14159,2.6,2.2,1.8,1.57]:
  q['right_2']=p;d=fk(q)
  print('pitch',p)
  for n in ['Upper_Arm','Lower_Arm','Wrist_Pitch_Roll','Fixed_Jaw']:
   print(n,np.round(d[n][:3,3],3))
  print('jaw axes',np.round(d['Fixed_Jaw'][:3,:3],2))
