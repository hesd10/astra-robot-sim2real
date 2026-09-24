"""Regenerate the approved result teaser from release data and included images."""
from pathlib import Path
import json
import statistics
import hashlib
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch
from matplotlib.path import Path as MplPath
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
HERE = REPO/'paper/figures'
HERE.mkdir(parents=True,exist_ok=True)
W, TOP, BOTTOM = 14.0, 1.04, 10.16
H = BOTTOM - TOP
BG, INK, MUTED = '#ffffff', '#182b3b', '#52616d'
BLUE, ORANGE, PURPLE = '#146caa', '#b55a12', '#70529c'
BLUE_BG, ORANGE_BG, PURPLE_BG = '#edf5fc', '#fff5e9', '#f3eff8'
GREY = '#8d9eae'
plt.rcParams.update({'font.family':'DejaVu Sans', 'pdf.fonttype':42, 'svg.fonttype':'none'})
fig = plt.figure(figsize=(W,H), facecolor=BG)
ax = fig.add_axes([0,0,1,1]); ax.set_xlim(0,W); ax.set_ylim(BOTTOM,TOP); ax.axis('off')

def text(x,y,s,size=16,color=INK,weight='normal',ha='left',va='center',**kw):
    return ax.text(x,y,s,fontsize=size,color=color,fontweight=weight,ha=ha,va=va,**kw)

def box(x,y,w,h,fc,ec='none',r=.1):
    p=FancyBboxPatch((x,y),w,h,boxstyle=f'round,pad=0,rounding_size={r}',
                    facecolor=fc,edgecolor=ec,lw=.9)
    ax.add_patch(p);return p

def arrow(x1,y1,x2,y2,color,scale=15):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle='-|>',
                 mutation_scale=scale,linewidth=1.7,color=color))

def mean(block,condition):
    data=json.loads((REPO/'results'/f'{block}.json').read_text())
    rows=[x for x in data if x['condition']==condition]
    assert rows and all(x['success'] for x in rows)
    return statistics.mean(x['seconds'] for x in rows),len(rows)

sim_base,n=mean('fixed-start','I0E0');assert n==3
real_base,n=mean('real','A');assert n==3
sim_body,_=mean('fixed-start','I3E0');sim_exp,_=mean('fixed-start','I0E3')
real_body,_=mean('real','B');real_exp,_=mean('real','C')
free,n=mean('local-skills','FREE');assert n==9
step,_=mean('local-skills','STEP');loop,_=mean('local-skills','LOOP')
measurements={}

text(2.86,1.25,'ROBOT KNOWLEDGE',size=18,weight='bold',color=BLUE)
text(8.42,1.25,'SYNCHRONIZED EXPERIENCE',size=18,weight='bold',color=ORANGE)

SIM_IMAGE=REPO/'media/simulation-local-state-S1.png'
REAL_IMAGE=REPO/'media/D3-approach.jpg'

def scene(path,x,y,w,h,limits=None):
    a=fig.add_axes([x/W,1-(y-TOP+h)/H,w/W,h/H])
    im=Image.open(path)
    a.imshow(im)
    if limits:
        a.set_xlim(*limits[0]);a.set_ylim(*limits[1])
    a.set_aspect('equal');a.axis('off')

text(.35,1.77,'Simulation',size=19,weight='bold')
scene(SIM_IMAGE,.42,2.04,2.02,1.85,((300,650),(695,100)))
arrow(1.37,4.06,1.37,4.70,MUTED,19)
text(1.54,4.38,'sim2real',size=14,weight='bold',color=MUTED)
text(.35,4.96,'Real',size=21,weight='bold')
scene(REAL_IMAGE,.40,5.23,2.05,1.88)

def metric(x,y,color,fill,label,baseline,result,with_label,key,local=False):
    w,h=5.22,2.65 if not local else 2.20
    box(x,y,w,h,fill)
    text(x+.20,y+.27,label,size=15.5,color=color,weight='bold')
    reduction=100*(1-result/baseline)
    measurements[key]={'baseline_seconds':baseline,'condition_seconds':result,
                       'mean_time_reduction_percent':reduction,'n_per_condition':9 if local else 3}
    # Each pair starts at zero. Height ratios exactly equal the time ratios.
    # Baselines are independently normalized; absolute means are above the bars.
    bottom=y+(2.20 if not local else 1.82)
    height=1.46 if not local else 1.06
    bar_width=.77
    left,right=x+.60,x+4.21
    top0,top1=bottom-height,bottom-height*result/baseline
    ax.plot([x+.20,x+w-.20],[bottom,bottom],color='#bdc8d1',lw=.9)
    for center,top,value,c,name in [(left,top0,baseline,GREY,'No skill' if local else 'Baseline'),(right,top1,result,color,with_label)]:
        ax.add_patch(Rectangle((center-bar_width/2,top),bar_width,bottom-top,facecolor=c,lw=0))
        unit=f'{value:.1f} s' if local else f'{value/60:.2f} min'
        text(center,top-.16,unit,size=15,color=INK,weight='bold',ha='center')
        text(center,bottom+.22,name,size=14,color=MUTED,ha='center')
    # A broad curved decline arrow sweeps from the high bar to the low bar.
    sx,sy=left+.59,top0+.10
    ex,ey=right-.59,top1+.10
    curve=MplPath([(sx,sy),(sx+.30,sy+.90*(ey-sy)),(ex,ey)],
                  [MplPath.MOVETO,MplPath.CURVE3,MplPath.CURVE3])
    ax.add_patch(FancyArrowPatch(path=curve,
                  arrowstyle='simple,tail_width=0.25,head_width=0.95,head_length=0.78',
                  mutation_scale=38 if not local else 32,facecolor=color,edgecolor='none',zorder=3))
    angle=-math.degrees(math.atan2(ey-sy,ex-sx))
    text((sx+ex)/2,(sy+ey)/2-.32 if not local else (sy+ey)/2-.33,
         f'−{reduction:.1f}%',size=30 if not local else 28,color=color,weight='bold',
         ha='center',rotation=angle,rotation_mode='anchor',zorder=4)

metric(2.65,1.56,BLUE,BLUE_BG,'Robot geometry + camera information',sim_base,sim_body,'With knowledge','simulation_assets')
metric(8.20,1.56,ORANGE,ORANGE_BG,'Images + actions + robot states',sim_base,sim_exp,'With experience','simulation_experience')
metric(2.65,4.78,BLUE,BLUE_BG,'Simulation knowledge on the real robot',real_base,real_body,'With knowledge','real_assets')
metric(8.20,4.78,ORANGE,ORANGE_BG,'Simulation experience on the real robot',real_base,real_exp,'With experience','real_experience')

ax.plot([.34,13.42],[7.66,7.66],color='#d7cde4',lw=1)
text(.35,8.04,'Local skills',size=20,weight='bold',color=PURPLE)
text(.35,8.47,'Simulation',size=14,color=PURPLE,weight='bold')
text(.35,8.78,'Near-button task',size=14,color=MUTED)
text(.35,9.27,'Generated routine',size=12.5,color=MUTED)
text(.35,9.54,'↓ parameterization',size=12.5,color=MUTED)
text(.35,9.81,'Reusable skills',size=12.5,color=PURPLE)
metric(2.65,7.82,PURPLE,PURPLE_BG,'STEP skill',free,step,'STEP','local_STEP',local=True)
metric(8.20,7.82,PURPLE,PURPLE_BG,'LOOP skill',free,loop,'LOOP','local_LOOP',local=True)

fig.savefig(HERE/'teaser.png',dpi=200,facecolor=BG)
fig.savefig(HERE/'teaser.pdf',facecolor=BG)
fig.savefig(HERE/'teaser.svg',facecolor=BG)
svg = HERE/'teaser.svg'
svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
plt.close(fig)
manifest={'figure':'teaser','status':'Approved front-page manuscript figure',
          'images':[
              {'path':str(SIM_IMAGE.relative_to(REPO)), 'role':'Illustrative simulator external view from local state S1, not a fixed-start trial frame', 'sha256':hashlib.sha256(SIM_IMAGE.read_bytes()).hexdigest()},
              {'path':str(REAL_IMAGE.relative_to(REPO)), 'role':'Illustrative external D3 video frame, not a frame from A/B/C comparisons', 'sha256':hashlib.sha256(REAL_IMAGE.read_bytes()).hexdigest()}],
          'main_metrics':measurements,
          'skills':{'baseline_seconds':free,'STEP_seconds':step,'LOOP_seconds':loop,'STEP_reduction_percent':100*(1-step/free),'LOOP_reduction_percent':100*(1-loop/free),'n_per_condition':9}}
(REPO/'results/teaser-provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Teaser regenerated from released per-trial means.')
