# Computation from supplied simulation reference; not calibrated real kinematics.
import numpy as np, xml.etree.ElementTree as ET
root=ET.parse('prior/body/robot/robot.xml').getroot()
mp={'right_'+str(i+1):s for i,s in enumerate(['Rotation_L','Pitch_L','Elbow_L','Wrist_Pitch_L','Wrist_Roll_L','Jaw_L'])}
mp.update({'left_'+str(i+1):s for i,s in enumerate(['Rotation_R','Pitch_R','Elbow_R','Wrist_Pitch_R','Wrist_Roll_R','Jaw_R'])})
mp.update(head_1='head_pan_joint',head_2='head_tilt_joint')
def quat(s):
 w,x,y,z=np.fromstring(s,sep=' ');return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
def rot(a,q):
 a=np.array(a);a=a/np.linalg.norm(a);x,y,z=a;K=np.array([[0,-z,y],[z,0,-x],[-y,x,0]]);return np.eye(3)+np.sin(q)*K+(1-np.cos(q))*(K@K)
def fk(q):
 q={mp[k]:v for k,v in q.items()}; out={}
 def walk(b,T):
  A=np.eye(4);A[:3,:3]=quat(b.get('quat','1 0 0 0'));A[:3,3]=np.fromstring(b.get('pos','0 0 0'),sep=' ');T=T@A
  for j in b.findall('joint'):
   R=np.eye(4);R[:3,:3]=rot(np.fromstring(j.get('axis','0 0 1'),sep=' '),q.get(j.get('name'),0));T=T@R
  out[b.get('name')]=T
  for c in b.findall('body'):walk(c,T)
 for b in root.find('worldbody').findall('body'):walk(b,np.eye(4))
 return out
if __name__=='__main__':
 import struct
 b=open('prior/body/robot/meshes/5528867073033eaa_Fixed_Jaw.stl','rb').read();n=struct.unpack('<I',b[80:84])[0];v=np.array([struct.unpack('<12f',b[84+i*50:84+i*50+48])[3:] for i in range(n)]).reshape(-1,3);print('jaw bounds',v.min(0),v.max(0))
 for q in [[-1.57,3.14,1.57,1.57,1.57],[-1.57,2,1.57,1.57,1.57],[-1.57,2,1,0.5,1.57]]:
  T=fk(dict(zip(['right_'+str(i) for i in range(1,6)],q)))['Fixed_Jaw'];print(q,'wrist',T[:3,3],'tip',(T@np.array([0,-.12,0,1]))[:3],'direction',-T[:3,1])
