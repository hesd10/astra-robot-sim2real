'use strict';
const $=id=>document.getElementById(id), token=document.querySelector('meta[name="calib-token"]').content;
let state=null, manifest=null, page='connect', joint='left_1', wheel='front_left', direction='forward', view='angle', frame=0, playing=false, tick=0, busy=false;
const checked=new Set();
let forceReference=false, forceSign=false, armGroup="left";
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(text,good=false){$('notice').textContent=text;$('notice').className=good?'good':'';$('notice').hidden=false;if(good)setTimeout(()=>{$('notice').hidden=true},4500)}
async function action(op,p={}){if(busy)return;if(state?.machines)p._robot=state.machines.selected;busy=true;try{const r=await fetch('/api/action/'+op,{method:'POST',headers:{'Content-Type':'application/json','X-Calib-Token':token},body:JSON.stringify(p)});const data=await r.json();if(!r.ok)throw Error(data.error);state=data;render();return data}catch(e){notice(e.message)}finally{busy=false}}
function showPage(name){page=name;document.querySelectorAll('.page').forEach(x=>x.hidden=x.id!=='page-'+name);document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x.dataset.page===name));render()}
function activeTask(kind,target){return state?.capture?.kind===kind&&state.capture.target===target}
function captureButtons(kind,target,label='开始采集'){if(state.capture){if(activeTask(kind,target))return `<button class="primary" data-action="finish">结束采集</button><button data-action="cancel">取消</button>`;return '<span class="small">先结束另一项正在进行的采集。</span>'}return `<button class="primary" data-start="${kind}" data-target="${target}" ${state.connected?'':'disabled'}>${label}</button>`}
function resultConfirm(target){const r=state.result;if(r?.kind!=='mapping'||r.target!==target)return '';return `<p>识别到 <b>${esc(state.motors[r.motor]?.short||r.motor)}</b>。这是刚才手动移动的部件。</p><button class="primary" data-confirm-target="${target}" data-motor="${esc(r.motor)}">确认对应关系</button> <button data-action="clear-result">重新采集</button>`}
function renderGuide(){if(!manifest)return;const spec=manifest[joint];$('guide-image').src=spec.views[view][frame];$('frame').value=frame;$('frame-label').textContent='+'+Math.round(spec.delta_rad*frame/12*180/Math.PI)+'°';$('guide-caption').textContent=frame===0?`参考姿态 · q = ${spec.reference_q===0?'0':'π'}`:'绿色部件沿 XML 正方向移动';$('play-animation').textContent=playing?'暂停动画':'播放正方向动画'}
function setJoint(key){joint=key;forceReference=false;playing=false;frame=0;render();renderGuide()}
function render(){if(!state)return;
 $('connection').textContent=state.demo?(state.connected?'离线演示 · 已连接':'离线演示'):state.connected?'电机读数已连接':state.machines?.serials?.length?'USB 已检测到 · 尚未打开读数':'未检测到机器人 USB';$('connection').className='pill'+(state.connected?' online':'');$('demo-label').textContent=state.demo?'演示模式 · 不访问实机':'';
 $('conn-count').textContent=state.connected?'已连接':'未打开读数';$('joint-count').textContent=`${state.summary.joints_complete} / 14`;$('base-count').textContent=state.summary.base_complete?'已完成':'待采集';$('joint-progress').textContent=`${state.summary.joints_complete} / 14 完成`;
 $('connect').disabled=state.connected;$('disconnect').disabled=!state.connected;$('release').disabled=!state.connected;
 $('last-update').textContent=state.connected?'读数更新于 '+new Date().toLocaleTimeString():'已保存的数据不会丢失';
 if(page==='connect')renderConnect();if(page==='joints')renderJoints();if(page==='base')renderBase();if(page==='export')renderExport();
}
function renderConnect(){const keys=Object.keys(state.motors);$('motor-count').textContent=keys.length+' 个';$('motors').innerHTML=keys.length?keys.map(k=>{const m=state.motors[k],v=state.live[k];return `<label class="motor-row"><input type="checkbox" data-motor-select="${esc(k)}" ${checked.has(k)?'checked':''}><span>${esc(m.short)}<small>${esc(m.model)} · 只读位置与扭矩状态</small></span><span>${v?.present??'—'}</span><span class="${v?.torque===0?'torque-off':'torque-on'}">${v?.torque===0?'已释放':'有扭矩'}</span></label>`}).join(''):'<div class="empty">连接后显示电机、当前读数与扭矩状态。</div>'}
function renderJoints(){
 const labels=state.groups||{left:'左臂',right:'右臂',head:'头部'};
 const keys=Object.keys(state.joints).filter(k=>state.joints[k].group===armGroup);
 const items=keys.map(k=>state.data.joints[k]||{});
 const mapped=items.every(j=>j.motor), referenced=items.every(j=>j.reference), stale=referenced&&state.connected&&items.some(j=>j.reference.epoch!==state.epoch);
 const signed=items.every(j=>j.sign), ranged=items.every(j=>j.limits);
 const stage=!mapped?1:!referenced||stale||forceReference?2:!signed||forceSign?3:!ranged?4:5;
 if(!keys.includes(joint))joint=keys[0];
 if(stage===3&&!forceSign&&state.data.joints[joint]?.sign)joint=keys.find(k=>!state.data.joints[k]?.sign)||keys[0];
 $('joint-list').innerHTML=Object.entries(labels).map(([g,label])=>{const list=Object.keys(state.joints).filter(k=>state.joints[k].group===g);const n=list.filter(k=>state.data.joints[k]?.limits).length;return `<button class="joint-item ${g===armGroup?'selected':''}" data-arm-group="${g}"><i class="dot ${n===list.length?'complete':''}"></i>${label}<span>${n} / ${list.length}</span></button>`}).join('')+'<p class="small">整组识别 → 整组粗摆<br>逐关节正方向 → 整组范围</p>';
 $('joint-title').textContent=stage===3?state.joints[joint].label:labels[armGroup]+' · 整组标定';
 $('joint-xml').textContent=stage===3?state.joints[joint].xml:(armGroup==='head'?'水平 q = π · 俯仰 q = 0':'整条手臂 q = 0');
 $('joint-data').textContent=JSON.stringify(Object.fromEntries(keys.map(k=>[k,state.data.joints[k]||{}])),null,2);
 let heading,description,buttons;
 if(stage===1){
  heading='动一动'+labels[armGroup]+'，识别整组电机';description=armGroup==='head'?'轻动头部，识别所在总线；水平和俯仰沿用 ID 7、8。':'轻动这条手臂，另一条保持不动。只需识别总线，六个关节沿用既有 ID 1–6 顺序，不必逐个识别。';
  const r=state.result;
  buttons=r?.kind==='group_mapping'&&r.target===armGroup?`<p>识别到总线 <b>${esc(r.serial)}</b>。${keys.map(k=>state.joints[k].label.split(' · ')[1]+' = ID '+r.motor_map[k].split(':').pop()).join('；')}。</p><button class="primary" data-confirm-group="${armGroup}">确认整组对应</button><button data-action="clear-result">重新识别</button>`:captureButtons('group_mapping',armGroup,'开始识别整组');
 }else if(stage===2){
  heading=stale?'重新连接后，重录整组参考姿态':'将'+labels[armGroup]+'整体摆成参考姿态';
  description=armGroup==='head'?'水平摆到 q = π、俯仰摆到 q = 0。保持约半秒，一次记录两个电机。':'照图将整条手臂（含夹爪）粗摆到 XML 零位。保持约半秒，一次记录六个电机，不必逐关节点击。';
  buttons=`<button class="primary" data-group-reference="${armGroup}" ${state.connected&&!state.capture?'':'disabled'}>整组已摆好，一次记录</button>`;
 }else if(stage===3){
  heading='逐关节确认正方向：'+state.joints[joint].label.split(' · ')[1];description='这一项仍逐关节进行。按当前动画的正方向移动约 5–15°，停住后结束，不要摆回起点。保存后自动进入下一个未完成关节。';
  buttons=captureButtons('positive',joint,'开始记录本关节正方向');
 }else if(stage===4){
  heading='一次采集'+labels[armGroup]+'的全部关节范围';description='点击开始后，用任意顺序手动扫过各关节的两个可用端点。整组同时跟踪，下表实时显示范围。不需逐关节开始／结束；缺少的范围可补测，已保存范围保留。';
  buttons=captureButtons('group_range',armGroup,'开始整组范围采集');
 }else{heading=labels[armGroup]+'已完成';description='整组参考、各关节正方向与可用范围均已保存。';buttons='<button class="primary" data-action="next-group">下一组 →</button><button data-group-rereference="'+armGroup+'">重录整组参考姿态</button><button data-group-clear-range="'+armGroup+'">重测整组范围</button>';}
 let signChoices=stage===3?'<div class="sign-choices">'+keys.map(k=>`<button class="${k===joint?'secondary':''}" data-sign-joint="${k}">${esc(state.joints[k].label.split(' · ')[1])}${state.data.joints[k]?.sign?' ✓':''}</button>`).join('')+'</div>':'';
 const table='<div class="group-table"><table><thead><tr><th>关节</th><th>当前读数</th><th>参考读数</th><th>正方向</th><th>范围 / °</th></tr></thead><tbody>'+keys.map(k=>{const j=state.data.joints[k]||{},v=state.live[j.motor],stat=state.capture?.kind==='group_range'&&state.capture.target===armGroup?state.capture.stats[j.motor]:null;let bounds='待采集';if(stat&&j.sign){const a=[stat.low,stat.high].map(x=>(j.reference.reference_q+j.sign*(x-j.reference.continuous)*2*Math.PI/4096)*180/Math.PI).sort((a,b)=>a-b);bounds=a.map(x=>x.toFixed(1)).join(' ～ ');}else if(j.limits)bounds=[j.limits.usable_min_rad,j.limits.usable_max_rad].map(x=>(x*180/Math.PI).toFixed(1)).join(' ～ ');return `<tr><td>${esc(state.joints[k].label.split(' · ')[1])}</td><td>${v?.present??'—'}</td><td>${j.reference?j.reference.continuous.toFixed(1):'—'}</td><td>${j.sign?j.sign>0?'+':'−':'待测'}</td><td>${bounds}</td></tr>`}).join('')+'</tbody></table></div>';
 $('joint-task').innerHTML=`<span class="step-number">${['','01 / 整组对应','02 / 整组参考姿态','03 / 各关节正方向','04 / 整组范围','完成'][stage]}</span><h2>${heading}</h2><p>${description}</p>`+signChoices+table;
 if($('joint-actions').dataset.last!==buttons){$('joint-actions').innerHTML=buttons;$('joint-actions').dataset.last=buttons;}
 $('capture-status').hidden=!state.capture;
 if(state.capture){$('capture-status').textContent='采集中 · '+(state.capture.kind==='group_range'?'本组全部关节同时跟踪，可任意顺序手动扫动。':'手动移动，程序只读取。');}
 const rejected=state.result?.kind==='group_range'&&state.result.target===armGroup?state.result.rejected:{};
 if(Object.keys(rejected||{}).length)$('joint-task').insertAdjacentHTML('beforeend','<p class="range-warning">仍需补测：'+Object.keys(rejected).map(k=>esc(state.joints[k].label.split(' · ')[1])).join('、')+'。</p>');
 $('play-animation').disabled=stage!==3;$('frame').disabled=stage!==3;
 if(stage!==3){playing=false;frame=0;joint=keys[0];}
 renderGuide();
}
function renderBase(){const base=state.data.base;$('dimension-saved').textContent=base.dimensions?`已保存：轮径 ${base.dimensions.diameter_mm} / 轮距 ${base.dimensions.track_mm} / 轴距 ${base.dimensions.wheelbase_mm} mm`:'尚未保存尺寸';
 for(const name of ['diameter_mm','track_mm','wheelbase_mm'])if(!$(name).value&&base.dimensions)$(name).value=base.dimensions[name];
 $('wheel-list').innerHTML=Object.entries(state.wheels).map(([k,label])=>{const m=state.data.wheels[k];return `<div class="wheel-row ${k===wheel?'active':''}"><span>${label}<small>${m?esc(state.motors[m.motor]?.short||m.motor):'尚未识别'}</small></span><button data-wheel="${k}">${m?'查看':'识别'}</button></div>`}).join('');
 const current=state.data.wheels[wheel];$('wheel-task').innerHTML=`<span class="tag">${state.wheels[wheel]}</span>`+(current?`<p>对应关系已保存。</p><button data-reset-wheel="${wheel}">重新识别此轮</button>`:resultConfirm(wheel)||`<p>只转动${state.wheels[wheel]}，其他轮子不动。</p><div class="actions">${captureButtons('mapping',wheel,'开始识别此轮')}</div>`);
 const arrows={forward:'↑',backward:'↓',left:'←',right:'→',ccw:'↶',cw:'↷'};
 $('direction-list').innerHTML='<div class="direction-grid">'+Object.entries(state.directions).map(([k,label])=>`<button class="direction-btn ${k===direction?'selected':''}" data-direction="${k}"><em>${arrows[k]}</em>${label}<span>${base.trials?.[k]?'✓ 已采集':'待采集'}</span></button>`).join('')+'</div>';
 $('base-task').innerHTML=`<p>当前：<b>${state.directions[direction]}</b>。${base.trials?.[direction]?'可重新采集这一方向。':'无需精确距离，缓慢单向移动即可。'}</p><div class="actions">${captureButtons('base',direction,'开始手推采集')}</div>`;
 if(state.capture?.kind==='base'){const delta=Object.entries(state.data.wheels).map(([w,m])=>{const x=state.capture.stats[m.motor];return x?state.wheels[w]+' '+(x.end-x.start)+' counts':''}).join(' · ');$('base-task').insertAdjacentHTML('beforeend','<div class="capture-status">正在读取：'+esc(delta)+'</div>');}
 $('base-result').textContent=base.solution?'✓ 六方向符号一致，名义运动学已保存':'';
}
function renderExport(){const sum=state.summary;$('summary-cards').innerHTML=`<article class="card stat-card"><h3>机械臂与头部</h3><b>${sum.joints_complete}<span> / 14</span></b><span>参考姿态 · 符号 · 可用范围</span></article><article class="card stat-card"><h3>底盘被动标定</h3><b>${sum.base_complete?'完成':'待完成'}</b><span>六方向检查与名义运动学</span></article><article class="card stat-card"><h3>主动控制验收</h3><b>尚未进行</b><span>本工具不发送运动指令</span></article>`;
 $('export-summary').innerHTML=(sum.passive_complete?'<p>被动标定项目已完成，可以导出。</p>':'<p>可以导出当前进度；未完成项会明确标记。</p>')+'<ul class="checklist">'+(sum.missing_joints.length?'<li>待完成关节：'+esc(sum.missing_joints.join('、'))+'</li>':'')+sum.outstanding.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>';
 $('workspace').textContent=state.workspace;$('camera-status').textContent=state.data.camera.status==='not_imported'?'尚未导入，不影响手动关节与底盘采集。':'已导入参考文件；未验证当前安装配置。';
}
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;
 if(b.dataset.page)return showPage(b.dataset.page);
 if(b.dataset.armGroup){if(state.capture)return notice('请先结束或取消当前采集。');armGroup=b.dataset.armGroup;forceReference=false;forceSign=false;playing=false;frame=0;render();return}
 if(b.dataset.confirmGroup){await action('group_mapping_confirm',{group:b.dataset.confirmGroup});render();return}
 if(b.dataset.groupReference){if(forceReference&&!confirm('整组姿态已摆好？重新记录后要重测本组的正方向和范围。'))return;const r=await action('group_reference',{group:b.dataset.groupReference});if(r){forceReference=false;forceSign=false;frame=0;render();playing=true;notice('整组参考读数已保存。接下来逐关节确认正方向。',true);}return}
 if(b.dataset.signJoint){if(state.capture)return notice('请先结束当前关节的采集。');joint=b.dataset.signJoint;forceSign=true;frame=0;playing=true;render();return}
 if(b.dataset.groupRereference){forceReference=true;forceSign=false;playing=false;frame=0;render();return}
 if(b.dataset.groupClearRange){if(confirm('重新测量本组范围？参考姿态和正方向保留。'))await action('group_reset',{group:b.dataset.groupClearRange,scope:'range'});return}
 if(b.dataset.action==='next-group'){const groups=['left','right','head'],i=groups.indexOf(armGroup);if(i===2)showPage('base');else{armGroup=groups[i+1];forceReference=false;forceSign=false;render();}return}

 if(b.dataset.joint)return setJoint(b.dataset.joint);
 if(b.dataset.view){view=b.dataset.view;document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('chosen',x===b));renderGuide();return}
 if(b.dataset.select){checked.clear();for(const [k,m] of Object.entries(state?.motors||{})){const v=b.dataset.select;if((v==='arms'&&m.id<=6)||(v==='head'&&m.id>=7&&m.id<=8)||(v==='wheels'&&m.model==='sts3250'))checked.add(k)}renderConnect();return}
 if(b.dataset.start){await action('capture_start',{kind:b.dataset.start,target:b.dataset.target});return}
 if(b.dataset.confirmTarget){await action('mapping_confirm',{target:b.dataset.confirmTarget,motor:b.dataset.motor});frame=0;playing=false;renderGuide();return}
 if(b.dataset.reference){if(forceReference&&!confirm('姿态已按参考图摆好？保存后需要重新采集该关节的方向和范围。'))return;forceReference=false;const r=await action('reference',{target:b.dataset.reference});if(r){notice('参考姿态已保存。接下来按动画确认正方向。',true);frame=0;playing=true;}return}
 if(b.dataset.rereference){forceReference=true;playing=false;frame=0;render();return}
 if(b.dataset.wheel){wheel=b.dataset.wheel;renderBase();return}
 if(b.dataset.resetWheel){if(confirm('重新识别该轮会清除底盘六方向采集，继续？'))await action('reset_target',{target:b.dataset.resetWheel});return}
 if(b.dataset.direction){direction=b.dataset.direction;renderBase();return}
 if(b.dataset.action==='finish'){const r=await action('capture_finish');if(r?.result?.kind==='positive'&&r.result.ok){forceSign=false;frame=0;render();playing=Object.keys(state.joints).some(k=>state.joints[k].group===armGroup&&!state.data.joints[k]?.sign);}if(r?.result?.ok)notice('采集已保存。',true);else if(r?.result?.partial)notice('已保存有效范围，请补测表中未完成项。');return}
 if(b.dataset.action==='cancel'||b.dataset.action==='clear-result'){await action('capture_cancel');return}
 if(b.dataset.action==='next-joint'){const keys=Object.keys(state.joints),i=keys.indexOf(joint);if(i<keys.length-1)setJoint(keys[i+1]);else showPage('base');return}
});
$('connect').onclick=async()=>{const r=await action('connect');if(r)notice(r.demo?'离线演示已连接，不访问实机。':'已只读连接，寄存器配置与备份一致。',true)};
$('disconnect').onclick=()=>action('disconnect');
$('motors').onchange=e=>{const k=e.target.dataset.motorSelect;if(k)e.target.checked?checked.add(k):checked.delete(k)};
$('release').onclick=async()=>{if(!checked.size)return notice('先勾选要释放的电机。');if(!$('supported').checked)return notice('请先托住所选部件，再勾选确认。');const r=await action('release',{motors:[...checked],supported:true});if(r){$('supported').checked=false;notice('所选电机已释放。不会自动恢复扭矩。',true)}};
$('show-reference').onclick=()=>{playing=false;frame=0;renderGuide()};$('play-animation').onclick=()=>{playing=!playing;renderGuide()};$('frame').oninput=()=>{playing=false;frame=Number($('frame').value);renderGuide()};
$('reset-joint').onclick=()=>{if(confirm('清除本组对应关系、参考姿态、方向和范围？原采集日志仍保留。'))action('group_reset',{group:armGroup,scope:'mapping'})};
$('save-dimensions').onclick=async()=>{const p={pattern_confirmed:$('pattern_confirmed').checked,direct_drive_confirmed:$('direct_drive_confirmed').checked};for(const k of ['diameter_mm','track_mm','wheelbase_mm'])p[k]=Number($(k).value);const r=await action('dimensions',p);if(r)notice('尺寸已保存。',true)};
$('solve-base').onclick=async()=>{const r=await action('solve_base');if(r)notice('六方向符号一致，名义运动学已保存。',true)};
$('import-camera').onclick=async()=>{try{const files=[];for(const f of $('camera-files').files){if(f.size>2e6)throw Error('单个文件请小于 2 MB');const bytes=new Uint8Array(await f.arrayBuffer());let text='';for(const x of bytes)text+=String.fromCharCode(x);files.push({name:f.name,data:btoa(text)})}const r=await fetch('/api/camera_import',{method:'POST',headers:{'Content-Type':'application/json','X-Calib-Token':token},body:JSON.stringify({files,note:$('camera-note').value})});const data=await r.json();if(!r.ok)throw Error(data.error);state=data;render();notice('参考文件已保存，保留未验证标记。',true)}catch(e){notice(e.message)}};
setInterval(()=>{if(playing&&page==='joints'){tick++;if(tick%2===0){frame=(frame+1)%17;if(frame>12)frame=0;renderGuide()}}},110);
async function poll(){try{const r=await fetch('/api/state');if(!r.ok)throw Error('无法读取服务状态');state=await r.json();render();if(state.error)notice(state.error)}catch(e){$('connection').textContent='服务连接中断';notice('服务连接中断。已释放的电机不会自动恢复扭矩。')}setTimeout(poll,600)}
fetch('/guides/manifest.json').then(r=>r.json()).then(m=>{manifest=m;renderGuide()}).catch(()=>notice('模型图示未生成，请运行 render_guides.py。'));poll();
