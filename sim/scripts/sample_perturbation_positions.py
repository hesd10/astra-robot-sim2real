"""Operator-only geometric sampling; never runs a subject or changes frozen trials."""
import hashlib,json,math,random
from pathlib import Path
import mujoco
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'studies/position-perturbation-001'
def main():
    OUT.mkdir(exist_ok=False)
    refpath=ROOT/'studies/body-experience-001/private-initial-reference.json'
    modelpath=ROOT/'models/elevator_four_mecanum.xml'
    ref=json.loads(refpath.read_text());m=mujoco.MjModel.from_xml_path(str(modelpath));d=mujoco.MjData(m)
    d.qpos[:]=ref['qpos'];mujoco.mj_forward(m,d)
    q=int(m.joint('base_free').qposadr[0]);origin=np.array(ref['qpos'][q:q+2]);rot=d.body('chassis').xmat.reshape(3,3).copy()
    robot=set()
    for b in range(m.nbody):
        a=b
        while a:
            if m.body(a).name=='chassis':robot.add(b);break
            a=int(m.body_parentid[a])
    def collision(offset):
        d.qpos[:]=ref['qpos'];d.qpos[q:q+2]+=offset;mujoco.mj_forward(m,d)
        bad=[]
        for c in d.contact:
            g1,g2=int(c.geom1),int(c.geom2)
            if (int(m.geom_bodyid[g1]) in robot)==(int(m.geom_bodyid[g2]) in robot):continue
            if 'floor' in [m.geom(g1).name,m.geom(g2).name]:continue
            if c.dist<=0:bad.append([m.geom(g1).name,m.geom(g2).name,float(c.dist)])
        return bad
    assert not collision(np.zeros(2))
    rng=random.Random(20260920);attempts=[];points=[]
    for radius in [.1,.5,1.]:
        for attempt in range(1,10001):
            angles=[rng.uniform(0,360) for _ in range(3)]
            separations=[abs((angles[i]-angles[j]+180)%360-180) for i in range(3) for j in range(i)]
            record={'radius_m':radius,'attempt':attempt,'angles_deg':angles,'min_separation_deg':min(separations)}
            if min(separations)<60:
                record.update(accepted=False,reason='pairwise angular separation below 60 degrees');attempts.append(record);continue
            offsets=[radius*np.array([math.cos(math.radians(a)),math.sin(math.radians(a))]) for a in angles]
            bad=[collision(o) for o in offsets]
            # Check a constructive path to the known feasible baseline, at <=1cm spacing.
            pathbad=[]
            for o in offsets:
                pathbad.append(next((hit for f in np.linspace(0,1,math.ceil(radius/.01)+1) if (hit:=collision(o*f))),[]))
            if any(bad) or any(pathbad):
                record.update(accepted=False,reason='robot-environment penetration at start or sampled return corridor',contacts=bad,path_contacts=pathbad);attempts.append(record);continue
            record.update(accepted=True);attempts.append(record)
            for i,(a,o) in enumerate(zip(angles,offsets),1):
                ident=f'R{round(radius*100):03d}-P{i}';world=origin+o;body=rot[:2,:2].T@o
                point={'id':ident,'radius_m':radius,'angle_world_deg':a,'offset_world_xy_m':o.tolist(),'offset_initial_body_forward_left_m':body.tolist(),'world_xy_m':world.tolist(),'min_group_separation_deg':min(separations),'min_group_chord_m':2*radius*math.sin(math.radians(min(separations)/2)),'initial_penetrating_environment_contacts':[],'return_corridor_sample_spacing_max_m':.01,'return_corridor_penetrating_environment_contacts':[]}
                points.append(point)
                setup={'name':ident,'description':'Operator-only frozen random translation candidate; yaw and home posture unchanged. No target coordinates supplied to subject.','initialization':{'standoff_m':2.4-float(o[1]),'lateral_m':.75+float(o[0]),'yaw_deg':8.0}}
                (OUT/'setups').mkdir(exist_ok=True);(OUT/'setups'/f'{ident}.json').write_text(json.dumps(setup,indent=2)+'\n')
            break
        else:raise RuntimeError('Sampling exhausted')
    result={'study':'position-perturbation-001','status':'positions_selected_experiments_not_started','seed':20260920,'algorithm':'Python random.Random; independent full triplets uniform angles; reject entire triplet if pairwise separation <60deg or geometric check fails','origin_world_xy_m':origin.tolist(),'angles':'world +X =0deg, +Y =90deg; +Y points toward elevator wall','radii_m':[.1,.5,1.],'yaw_deg_unchanged':8.,'joint_posture_unchanged':True,'geometry_check':'MuJoCo static collision at translated settled baseline, floor support excluded; straight return corridor sampled at <=1cm, not a dynamic execution or real-hardware clearance certification','source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [refpath,modelpath]},'points':points,'sampling_attempts':attempts}
    (OUT/'positions.json').write_text(json.dumps(result,indent=2)+'\n')
    # Standalone SVG plan view: x horizontal, y towards wall at top.
    def xy(v):return (420+(v[0]-origin[0])*220,380-(v[1]-origin[1])*220)
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="850" height="780" viewBox="0 0 850 780"><rect width="850" height="780" fill="white"/><g font-family="sans-serif" font-size="14" fill="#203040">','<text x="35" y="30" font-size="21">Random initial positions: 10 / 50 / 100 cm</text>','<text x="35" y="55">Fixed yaw; minimum pairwise angle 60 degrees within each ring</text>']
    colors={.1:'#118577',.5:'#cc7900',1.:'#6e48bb'}
    for r in [.1,.5,1.]:svg.append(f'<circle cx="420" cy="380" r="{r*220}" fill="none" stroke="{colors[r]}" stroke-dasharray="5 5"/>')
    svg.append('<circle cx="420" cy="380" r="4" fill="#111"/><text x="432" y="399">Original start</text>')
    for p in points:
        x,y=xy(p['world_xy_m']);color=colors[p['radius_m']];svg.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/><text x="{x+8}" y="{y-8}" fill="{color}">{p["id"]}</text>')
    # Enlarged inner ring inset avoids unreadable 10cm labels.
    svg.append('<rect x="25" y="555" width="205" height="195" fill="white" stroke="#ccc"/><text x="40" y="578">10 cm ring (enlarged)</text><circle cx="127" cy="665" r="55" fill="none" stroke="#118577" stroke-dasharray="4 4"/><circle cx="127" cy="665" r="3"/>')
    for p in points[:3]:
        o=p['offset_world_xy_m'];x=127+o[0]*550;y=665-o[1]*550;svg.append(f'<circle cx="{x}" cy="{y}" r="4" fill="#118577"/><text x="{x+5}" y="{y-6}">P{p["id"][-1]}</text>')
    svg+=['<path d="M735 180 L735 100 L730 110 M735 100 L740 110" stroke="#333" fill="none"/><text x="640" y="85">+Y toward elevator wall</text>','<text x="290" y="710">World +X points right. Coordinates and audit: positions.json</text>','<text x="290" y="735">All starts and sampled return corridors passed collision checks.</text>','</g></svg>']
    (OUT/'positions.svg').write_text('\n'.join(svg))
    lines=['# 随机站位采样记录','', '仅完成点位选择，未启动扰动实验。每档三个点；E0/E3使用完全相同站位。随机种子20260920，整组三角度均匀采样，不满足最小60°间隔时整组重抽。角度相对世界+X，世界+Y朝向电梯墙。机器人朝向不变。','', '|点位|半径cm|角度°|世界ΔX cm|世界ΔY cm|初始机身向前cm|初始机身向左cm|','|---|---:|---:|---:|---:|---:|---:|']
    for p in points:
        o=p['offset_world_xy_m'];f,l=p['offset_initial_body_forward_left_m'];lines.append(f'|{p["id"]}|{p["radius_m"]*100:.0f}|{p["angle_world_deg"]:.2f}|{o[0]*100:+.2f}|{o[1]*100:+.2f}|{f*100:+.2f}|{l*100:+.2f}|')
    lines+=['','几何验证：以原始settled qpos平移，检查机器人与环境的非地面穿透；到原站位的直线回程每不超过1cm采样检查。全部通过。该检查提供一条几何可行回程，不保证动态控制成功，也不代替真机现场检查。未使用Astra成绩、图像好坏或源轨迹重放结果筛点。所有拒绝记录见positions.json。','', 'setups仅为后续初始化文件；正式启动前还需分别产生对应私有初态参考，不能继续使用原站位reference来覆盖新站位。原实验冻结输入、模型及调度不变。']
    (OUT/'POSITIONS.zh-CN.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'points':points,'attempts':len(attempts)},indent=2))
if __name__=='__main__':main()
