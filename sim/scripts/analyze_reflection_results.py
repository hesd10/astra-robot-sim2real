"""Offline descriptive analysis. Does not launch trials or modify frozen inputs."""
import json,statistics,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'studies/experience-reflection-001'
B=ROOT/'reports/batches'
def read(p):return json.loads(p.read_text())
def mean(v):return statistics.mean(v)
def main():
    a=read(B/'experience-reflection-001/status.json');b=read(B/'experience-reflection-001-round2/status.json')
    assert len(a['completed'])==12 and len(b['completed'])==18
    assert len(a['reviewed_pairs'])==6 and len(b['reviewed_pairs'])==6
    historical=read(OUT/'baselines.json');rounds={1:historical+a['completed'],2:b['completed']}
    for t in a['completed']+b['completed']:
        r=t['result'];assert r['initial_pose_verified'] and r['physical_success'] and not r['wrong_button'] and r['fault'] is None
    metrics={}
    for rn,rows in rounds.items():
        metrics[rn]={}
        for c in ['E3','C','R']:
            v=[t['result'] for t in rows if t['condition']==c]
            metrics[rn][c]={'n':len(v),'successes':sum(x['success_and_correct_declaration'] for x in v),
              **{k:mean(x[k] for x in v) for k in ['native_execution_wall_seconds','motion_commands','observation_groups','tool_seconds','outside_tool_seconds','first_base_seconds']},
              'mean_first_press_to_finish':mean(x['sim_seconds']-x['first_target_press_seconds'] for x in v),
              'mean_tokens':{k:mean(x['tokens_whole_session'][k] for x in v) for k in ['total','input','cached_input','noncached_input','output']}}
    points=[t['point'] for t in historical];paired=[]
    for p in points:
        v={rn:{t['condition']:t['result']['native_execution_wall_seconds'] for t in rows if t['point']==p} for rn,rows in rounds.items()}
        paired.append({'point':p,'rounds':v,'two_measurement_means':{c:mean(v[n][c] for n in [1,2]) for c in ['E3','C','R']}})
    data={'scope':'30 new runs plus 6 historical E3 baselines; all successful; descriptive only','round_metrics':metrics,'paired_points':paired,'round1':rounds[1],'round2':rounds[2]}
    (OUT/'TWO_MEASUREMENT_RESULTS.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    lines=['# 单轨迹经验精简与反思：两次测量结果','', '已完成用户授权的30次新试验：首轮12次C/R、第二轮18次E3/C/R；全部成功、无误按/故障。另复用6次历史E3，合计36条比较记录。所有12组配对/三条件结果都已查看新鲜成功头部图并审阅公开日志；本次不做第三轮。', '', '## 主要结果', '', '|测量|E3平均秒|C平均秒|R平均秒|C相对E3用时变化|R相对E3用时变化|C相对R用时变化|','|---|---:|---:|---:|---:|---:|---:|']
    for rn in [1,2]:
        m=metrics[rn];e,c,r=[m[k]['native_execution_wall_seconds'] for k in ['E3','C','R']]
        lines.append(f"|{rn}（{'E3历史' if rn==1 else '三条件同期'}）|{e:.2f}|{c:.2f}|{r:.2f}|{(c/e-1)*100:+.1f}%|{(r/e-1)*100:+.1f}%|{(c/r-1)*100:+.1f}%|")
    lines+=['','负值表示更快。第一轮C在4/6点快于R，第二轮6/6；合计10/12配对C更快。C相对E3第一轮3/6更快、第二轮3/6更快，因此不能称精简资料带来一致的全点提升。第二轮N100-P2仅相差1.15秒，不能过度解读其排序。', '', '## 按点列出两次测量','', '|点位|首轮历史E3|首轮C|首轮R|二轮同期E3|二轮C|二轮R|','|---|---:|---:|---:|---:|---:|---:|']
    for p in paired:
        v=p['rounds'];lines.append('|'+p['point']+'|'+'|'.join(f'{v[n][c]:.1f}' for n in [1,2] for c in ['E3','C','R'])+'|')
    lines+=['','每个条件每个点只有两条记录，其中E3第一条来自历史时段。以下两次均值只能作描述，不是两个同期重复的因果估计。','','|点位|E3两次均值秒|C两次均值秒|R两次均值秒|','|---|---:|---:|---:|']
    for p in paired:lines.append('|'+p['point']+'|'+'|'.join(f'{p["two_measurement_means"][c]:.1f}' for c in ['E3','C','R'])+'|')
    pooled={c:mean(p['two_measurement_means'][c] for p in paired) for c in ['E3','C','R']}
    lines.append('|六点平均|'+'|'.join(f'{pooled[c]:.1f}' for c in ['E3','C','R'])+'|')
    lines+=['','## 行为和延迟指标','', '|测量/条件|动作均值|观测组均值|工具内秒|工具外秒|首按至finish秒|','|---|---:|---:|---:|---:|---:|']
    for rn in [1,2]:
        for c in ['E3','C','R']:
            m=metrics[rn][c];lines.append(f'|{rn}/{c}|'+ '|'.join(f'{m[k]:.2f}' for k in ['motion_commands','observation_groups','tool_seconds','outside_tool_seconds','mean_first_press_to_finish'])+'|')
    lines+=['','总时间为native受试任务开始至finish，包含读资料、看图、写代码、调度、控制与确认，排除完成后的报告/导出。工具外不等于纯推理；观测组不等于模型决策次数，一次图像拼接或本地脚本内观察改变计数含义。首按与finish分开：R er001-t023和t030分别有约64.2和74.4秒首按后延迟，这影响整任务成绩，但不代表机械推进慢。', '', '## 全会话token均值','', '|测量/条件|累计总token|缓存输入|非缓存输入|输出|','|---|---:|---:|---:|---:|']
    for rn in [1,2]:
        for c in ['E3','C','R']:
            m=metrics[rn][c]['mean_tokens'];lines.append(f'|{rn}/{c}|'+ '|'.join(f'{m[k]:.0f}' for k in ['total','cached_input','noncached_input','output'])+'|')
    lines+=['','全会话token包含收尾和反复传入的上下文，不是源材料长度，也不能直接等同计费或新增计算。材料被压缩并不保证整个会话token更少。','', '## 证据支持的机制与局限','',
    '1. 所有条件普遍使用源机械臂工作姿态；历史图像提供目标/姿态/按压前后外观参照，底盘批量长度与横向纠偏依当前图像变化。未发现可把所有成功解释为整条底盘轨迹盲放的证据。',
    '2. C与R使用同源动作和图像，主要区别是guide的表达。R阅读反思并不证明每条建议引起了某个动作。在本任务/冻结版本下，增加反思解释没有观察到优于C的平均效率收益；这不否定所有反思方法。',
    '3. E3原始summary已经含定性经验，不能将比较称作无反思对有反思；C/R相对E3还同时改变了图像选择、资料组织和体积，不能隔离一个独立压缩变量。',
    '4. 首轮C er001-t005自写末段红像素闭环：4步约4.6秒本地执行，最终由Astra看图复核。第二轮同点C未再次出现该程序。它是值得提炼的机制案例，而非本研究已验证的可复用skill或sim2real能力。',
    '5. 相同点/条件跨轮波动明显，例如N010-P2 C从254.9到489.9秒，N100-P2 C从556.5到360.7、R从340.2到559.2秒。不要用早期局部均值或一条最快轨迹证明系统性提升。',
    '6. 历史E3与当前运行账户及时间段不同；第二轮三条件同期交错六种顺序，比较更直接，但仍各点一次。没有第三次重复、不估计可靠的同点方差、不作统计显著性宣称。测试点已在前研究见过，材料源轨迹不来自这些测试点，但不是全新盲测。',
    '7. 30/30在这一任务集成功不意味着一般可靠性100%。成功图中下键有时被遮挡，无误按还依赖评估事件；未将遮挡图单独视为完整无误按证明。', '',
    '## 后续方向（讨论记录，未启动）','',
    '当前只考虑I0。闭环skill暂留仿真：候选为末段按压激活、夹爪/按钮视觉对齐、接近面板；先验证对应阶段，再少量全程检查衔接。第一候选来自er001-t005的局部反馈程序；拟比较自行解决、动作封装、局部视觉闭环，Astra基线仍允许自写脚本，计入参数选择/写代码成本。开发与测试起始状态分开、恢复完整物理状态。9次探索/27次重复的方案仅为讨论，尚未授权执行。', '',
    '用户明确认为红光规则不适合直接迁真机，其他两个候选尚未仿真验证。sim2real近期主线是E3/C/R经验参照，非直接重放仿真动作；自主闭环skill须先在仿真验证收益和适用边界。没有进行任何真机动作。', '',
    '本轮全程保留冻结输入，没有根据正式成绩改经验，也没有将局部闭环新技能加入后续受试。源整理过程在PROCESS、SOURCE_LEDGER和SELECTION；逐组证据在first-measurement-reviews和second-measurement-reviews。']
    (OUT/'TWO_MEASUREMENT_ANALYSIS.zh-CN.md').write_text('\n'.join(lines)+'\n')
    archive=OUT/'second-measurement-reviews';archive.mkdir(exist_ok=True)
    for f in (B/'experience-reflection-001-round2/pair-reviews').glob('*.md'):shutil.copy2(f,archive/f.name)
    src=B/'experience-reflection-001/er001-t005-local-feedback-analysis.zh-CN.md'
    if src.exists():shutil.copy2(src,OUT/'EMERGENT_LOCAL_FEEDBACK.zh-CN.md')
    print(json.dumps({'round2':metrics[2],'pooled_descriptive':pooled},ensure_ascii=False))
if __name__=='__main__':main()
