"""Regenerate all manuscript statistics, tables and plots from the released rows."""
from pathlib import Path
import json,statistics as st
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
R=Path(__file__).resolve().parents[1];F=R/'paper/figures';F.mkdir(parents=True,exist_ok=True)
plt.rcParams.update({'font.size':10,'font.family':'DejaVu Sans','axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'savefig.bbox':'tight'})
colors=['#546376','#126c8a','#148f77','#c77830']
def load(n):return json.loads((R/'results'/f'{n}.json').read_text())
def stat(rows):
 v=[x['seconds'] for x in rows];return dict(n=len(v),successes=sum(x['success'] for x in rows),mean=st.mean(v),sd=st.stdev(v) if len(v)>1 else None,values=v)
def save(name):
 plt.savefig(F/(name+'.pdf'));plt.savefig(F/(name+'.png'),dpi=190);plt.close()
fixed=load('fixed-start');pp=load('perturbation');skills=load('local-skills');real=load('real')
assert [len(x) for x in [fixed,pp,skills,real]]==[30,18,27,12]
assert all(x['success'] for rows in [fixed,pp,skills,real] for x in rows)
fg={g:stat([r for r in fixed if r['condition']==g]) for g in dict.fromkeys(x['condition'] for x in fixed)}
rg={g:stat([r for r in real if r['condition']==g]) for g in 'ABCD'}
sg={g:stat([r for r in skills if r['condition']==g]) for g in ['FREE','STEP','LOOP']}
summary=dict(fixed=fg,real=rg,skills=sg,real_start_design='A/B/C and D1 share a nominal start; D2/D3 use different new starts')
(R/'results/summary.json').write_text(json.dumps(summary,indent=2)+'\n')
fig,axs=plt.subplots(1,2,figsize=(9,3.2))
for ax,groups,title in [(axs[0],['I0E0','I1E0','I2E0','I3E0'],'(a) Body information without experience'),(axs[1],['I0E0','I0E1','I0E2','I0E3'],'(b) Experience at minimum body information')]:
 for i,g in enumerate(groups):
  vals=fg[g]['values'];ax.bar(i,st.mean(vals)/60,color=colors[i],alpha=.8,width=.6)
  ax.scatter([i-.12,i,i+.12],[v/60 for v in vals],color='#142430',s=19,zorder=3)
 ax.set_xticks(range(4),groups);ax.set_ylim(0,24);ax.set_ylabel('Task time (min)');ax.set_title(title,fontsize=10)
fig.tight_layout();save('fixed-start')
fig,axs=plt.subplots(1,3,figsize=(9,3.1),sharey=True)
for panel,(ax,rad) in enumerate(zip(axs,[.1,.5,1])):
 points=list(dict.fromkeys(x['point'] for x in pp if x['radius_m']==rad));means=[]
 for i,p in enumerate(points):
  a=next(x['seconds'] for x in pp if x['point']==p and x['condition']=='I0E0');b=next(x['seconds'] for x in pp if x['point']==p and x['condition']=='I0E3');ax.plot([0,1],[a/60,b/60],'-o',lw=1.4,color=colors[i],label=p)
 ax.set_xticks([0,1],['E0','E3']);ax.set_xlim(-.3,1.3);ax.set_ylim(0,23);ax.set_title(f'({chr(97+panel)}) {rad*100:.0f} cm offset');ax.legend(fontsize=7,frameon=False)
axs[0].set_ylabel('Task time (min)');fig.tight_layout();save('perturbation')
fig,ax=plt.subplots(figsize=(8,3.3))
for j,g in enumerate(['FREE','STEP','LOOP']):
 for i,s in enumerate(['S1','S2','S3']):
  vals=[x['seconds'] for x in skills if x['condition']==g and x['state']==s];pos=i+(j-1)*.25
  ax.bar(pos,st.mean(vals),width=.23,color=colors[j],alpha=.82,label=g if i==0 else None);ax.scatter([pos-.05,pos,pos+.05],vals,s=18,color='#142430',zorder=3)
ax.set_xticks(range(3),['S1','S2','S3']);ax.set_ylabel('Local-task time (s)');ax.set_ylim(0,270);ax.legend(frameon=False,ncol=3);fig.tight_layout();save('local-skills')
fig,axs=plt.subplots(1,2,figsize=(9,3.3),gridspec_kw={'width_ratios':[1,1]})
for i,g in enumerate('ABC'):
 vals=rg[g]['values'];axs[0].bar(i,st.mean(vals)/60,width=.6,color=colors[i],alpha=.82);axs[0].scatter([i-.1,i,i+.1],[v/60 for v in vals],color='#142430',s=20,zorder=3)
axs[0].set_xticks([0,1,2],['A\nNo prior','B\nSim XML','C\nSim E3']);axs[0].set_ylim(0,18);axs[0].set_ylabel('Task time (min)');axs[0].set_title('(a) Same-start comparison (3 per condition)',fontsize=10)
for i,x in enumerate([x for x in real if x['condition']=='D']):
 axs[1].bar(i,x['seconds']/60,color=colors[3],width=.6);axs[1].text(i,x['seconds']/60+.2,f"{x['seconds']:.1f} s",ha='center',fontsize=9)
axs[1].set_xticks([0,1,2],['D1\nSource start','D2\nNew start 1','D3\nNew start 2']);axs[1].set_ylim(0,8);axs[1].set_ylabel('Task time (min)');axs[1].set_title('(b) Real experience at three starts',fontsize=10);fig.tight_layout();save('real-results')
fig,ax=plt.subplots(figsize=(9,3.1));ax.axis('off')
boxes=[(.02,.57,.26,.31,'BODY KNOWLEDGE\nXML, meshes, cameras'),(.37,.57,.26,.31,'EXPERIENCE\nImages + synchronized actions'),(.72,.57,.26,.31,'LOCAL SKILLS\nStep and visual-loop programs'),(.28,.06,.44,.29,'GPT-6-Astra + CURRENT OBSERVATIONS\nSelect, execute, inspect, adjust')]
for x,y,w,h,t in boxes:
 ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.012',facecolor='#edf4f5',edgecolor='#126c8a',lw=1.2));ax.text(x+w/2,y+h/2,t,ha='center',va='center',fontsize=9)
for x in [.15,.5,.85]:ax.annotate('',xy=(.5,.35),xytext=(x,.55),arrowprops={'arrowstyle':'->','color':'#546376'})
save('overview')
# Tables included by both the paper and report.
out=['\\begin{tabular}{lrrrr}\\toprule','Condition & $n$ & Mean (s) & SD (s) & Motion requests \\\\ \\midrule']
for g,v in fg.items():
 m=st.mean(x['motions'] for x in fixed if x['condition']==g);out.append(f'{g} & {v["n"]} & {v["mean"]:.1f} & {v["sd"]:.1f} & {m:.1f} \\\\')
out+=['\\bottomrule\\end{tabular}'];(R/'paper/fixed-table.tex').write_text('\n'.join(out)+'\n')
print('Verified counts: 30 fixed, 18 paired-offset, 27 local, 12 real. Figures regenerated.')
from PIL import Image
fig,axs=plt.subplots(1,3,figsize=(7.5,4.8))
for ax,name,title in zip(axs,['start','approach','near-button'],['(a) Video 0:00','(b) Video 2:30','(c) Video 5:15']):
 ax.imshow(Image.open(R/'media'/f'D3-{name}.jpg'));ax.set_title(title,fontsize=10);ax.axis('off')
fig.tight_layout();save('real-demonstration')
# Keep the front-page result scheme reproducible from the same released rows.
import runpy
runpy.run_path(str(R/'analysis/build_teaser.py'),run_name='__main__')
runpy.run_path(str(R/'analysis/build_scene_figure.py'),run_name='__main__')
runpy.run_path(str(R/'analysis/build_arm_pose_figure.py'),run_name='__main__')
runpy.run_path(str(R/'analysis/build_simulation_sequence.py'),run_name='__main__')
