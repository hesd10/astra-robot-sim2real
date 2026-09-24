'use strict';
const flowPages=['machines','connect','joints','base','cameras','parameters','validation','ready'];
function cameraLabel(path){const port=path.match(/usb-\d+:([^:]+):/);return state?.machines?.camera_labels?.[path]||('USB '+(port?port[1]:path));}
const oldShowPage=showPage;
showPage=function(name){oldShowPage(name);const i=flowPages.indexOf(name);$('flow-step').textContent=i<0?'独立工具':`第 ${i+1} / ${flowPages.length} 步 · 可跳过已有标定`; $('flow-back').disabled=i<=0;$('flow-next').disabled=i<0||i===flowPages.length-1;};
$('flow-back').onclick=()=>showPage(flowPages[flowPages.indexOf(page)-1]);
$('flow-next').onclick=()=>showPage(flowPages[flowPages.indexOf(page)+1]);

let machineStamp='', machineJobStamp='', machineBusy=false;
async function machineAction(op,data={}){
 if(machineBusy&&op!=='stop')return;machineBusy=true;
 try{
  if(!['create','load','stop'].includes(op)){data._robot=state?.machines?.selected;data._revision=state?.machines?.profile?.revision;}
  if(['initial','snapshot','ready'].includes(op))data.serials=[...document.querySelectorAll('[data-serial]:checked')].map(x=>x.dataset.serial);
  const r=await fetch('/api/machine/'+op,{method:'POST',headers:{'Content-Type':'application/json','X-Calib-Token':token},body:JSON.stringify(data)}),d=await r.json();if(!r.ok)throw Error(d.error);
  state=d;if(['load','create'].includes(op)){checked.clear();machineStamp='';}render();notice('已处理；没有自动恢复参数或释放 torque。',true);
 }catch(e){notice(e.message)}finally{machineBusy=false}
}
const originalRender=render;
render=function(){originalRender();const m=state?.machines;if(!m)return;
 $('machine-label').textContent=m.selected||'未选择';const p=m.profile;
 const stamp=JSON.stringify([m.names,m.selected,p?.revision,p?.parameters_applied_hash,m.camera_devices]);
 if(stamp!==machineStamp){machineStamp=stamp;
  $('machine-select').innerHTML=m.names.map(n=>`<option ${n===m.selected?'selected':''}>${esc(n)}</option>`).join('');
  $('machine-info').textContent=`当前：${m.selected} · 版本 ${p?.revision} · ${state.demo?'离线演示，禁止实机操作':'实机配置，点击才连接'} · ${p?.parameters_applied_hash?'已记录参数应用；重连仍需核对':'参数计划尚未在此流程应用到电机'}`;
  $('machine-backup').textContent=p?.initial_backup?'已绑定初始备份（保留原始文件）':'尚无初始备份，不能连接新机器进行标定';
  $('machine-versions').textContent=JSON.stringify({验收:p?.validation,历史版本:p?.revisions},null,2);
  const selection=new Set([...document.querySelectorAll('[data-serial]:checked')].map(x=>x.dataset.serial));
  $('machine-serials').innerHTML=m.serials.map(n=>`<label class="check"><input type="checkbox" data-serial="${esc(n)}" ${selection.has(n)?'checked':''}>${esc(m.serial_labels?.[n]||n)}</label>`).join('')||'<p>未检测到串口；可离线编辑已有配置。</p>';
  const cameras=[...new Set([...(m.camera_devices||[]),...Object.values(p?.camera?.devices||{})])];
  $('machine-camera-selects').innerHTML=Object.entries({head:'头部',left_wrist:'左腕',right_wrist:'右腕'}).map(([r,n])=>`<label>${n}<select id="camera-role-${r}">${cameras.map(d=>`<option value="${esc(d)}" ${p?.camera?.devices?.[r]===d?'selected':''}>${esc(cameraLabel(d))}</option>`).join('')}</select></label>`).join('');
  $('machine-download-ready').hidden=!p?.latest_ready&&!p?.backup_index;
  const groups={};for(const v of Object.values(p?.parameters?.motors||{})){const label=v.role.startsWith('head')?'头部':v.role.startsWith('front')||v.role.startsWith('rear')?'底盘四轮':v.role.endsWith('_4')||v.role.endsWith('_5')?'双腕':'肩、肘与夹爪';groups[label]=v}
  $('machine-parameter-table').innerHTML='<table><tr><th>分组</th><th>加速度寄存器</th><th>速度寄存器</th></tr>'+Object.entries(groups).map(([n,v])=>`<tr><td>${esc(n)}</td><td>${v.acceleration}</td><td>${v.speed}</td></tr>`).join('')+'</table>';
  $('machine-parameters').textContent=p?.parameters?JSON.stringify(p.parameters,null,2):'完成被动标定后生成。';
 }
 $('machine-job').textContent=m.job?`${m.job.kind} · ${m.job.status} · ${m.job.message}`:'空闲';
 $('machine-live-job').textContent=m.job?.status==='running'?m.job.message:'空闲 · 不会自动恢复参数或释放 torque';
 const jstamp=JSON.stringify(m.job);if(jstamp!==machineJobStamp){machineJobStamp=jstamp;$('machine-job-result').textContent=m.job?JSON.stringify(m.job.result||m.job.error||{},null,2):'';
 if(m.job?.kind==='camera_capture'&&m.job.status==='completed')$('machine-camera-images').innerHTML=Object.entries(m.job.result).map(([i,c])=>`<figure><img width="280" src="${esc(c.url)}?t=${c.captured}"><figcaption>相机 ${Number(i)+1} · ${esc(cameraLabel(c.device))}</figcaption></figure>`).join('');}
 document.querySelectorAll('[data-machine]').forEach(b=>b.disabled=m.job?.status==='running'&&b.dataset.machine!=='stop');
};
$('machine-create').onclick=()=>machineAction('create',{name:$('machine-name').value.trim()});
$('machine-load').onclick=()=>machineAction('load',{name:$('machine-select').value});
$('machine-camera-save').onclick=()=>machineAction('save_cameras',{devices:Object.fromEntries(['head','left_wrist','right_wrist'].map(r=>[r,$('camera-role-'+r).value]))});
document.querySelectorAll('[data-machine]').forEach(b=>b.onclick=()=>machineAction(b.dataset.machine));
document.querySelectorAll('[data-accept]').forEach(b=>b.onclick=()=>machineAction('accept',{section:b.dataset.accept}));
showPage('machines');
