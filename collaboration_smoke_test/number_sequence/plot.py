"""Plot saved exact-position scores without running any agents."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import PercentFormatter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('batch',type=Path)
    args = parser.parse_args()
    rows = json.loads((args.batch/'summary.json').read_text())
    manifest = json.loads((args.batch/'manifest.json').read_text())
    label = 'GPT-5.6 Luna' if 'luna' in manifest.get('model','') else 'GLM 5.3 Flash'
    sequential = manifest.get('execution') == 'sequential_teams_concurrent_agents'
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(11,6.6))
    fig.subplots_adjust(left=.1,right=.97,bottom=.24,top=.78)
    fig.text(.1,.925,'Number-sequence coordination',fontsize=24,weight='bold',color='#172b42')
    fig.text(.1,.865,f'Correct sorted positions by team size · {label}',fontsize=13,color='#52657b')
    x = [r['agents'] for r in rows]
    y = [r['score_percent'] for r in rows]
    ax.plot(x,y,color='#2563eb',linewidth=2.3,marker='o',markersize=8)
    stopped = [r for r in rows if r['submitted'] < r['agents']]
    if stopped:
        ax.scatter([r['agents'] for r in stopped],[r['score_percent'] for r in stopped],marker='X',s=100,
                   color='#c83c4d',zorder=3,label='Includes agents stopped by limits or errors')
        ax.legend(loc='lower left',fontsize=9,frameon=False)
    for r in rows:
        ax.annotate(f"{r['score_percent']:.1f}%",(r['agents'],r['score_percent']),xytext=(0,12),
                    textcoords='offset points',ha='center',fontsize=11)
    ax.set(xlim=(min(x)-.4,max(x)+.4),ylim=(-5,112),xlabel='Agents sharing one workspace',ylabel='Numbers in correct sorted positions')
    ax.set_xticks(x)
    ax.set_yticks([0,20,40,60,80,100])
    ax.yaxis.set_major_formatter(PercentFormatter(100))
    ax.set_axisbelow(True)
    ax.grid(alpha=.2)
    ax.spines[['top','right']].set_visible(False)
    if sequential:
        execution_note = f"One selected rerun per size. Sequential teams; concurrent agents; {manifest['minutes']}-minute deadline."
        caveat = 'Selected after earlier scores below 100%. Provider retries may affect results; see the run report.'
    else:
        execution_note = f"One fresh attempt per size. Teams ran in parallel, with {manifest['max_api_connections']} API slots total."
        caveat = 'See manifest for limits; live deadline changes are recorded in deadline_overrides.json.'
    fig.text(.1,.13,execution_note,fontsize=10,color='#52657b')
    fig.text(.1,.09,caveat,fontsize=10,color='#52657b')
    fig.text(.1,.05,'Score = correct positions in the full sorted roster ÷ team size. Missing submissions receive no credit.',fontsize=10,color='#52657b')
    for extension in ('png','svg','pdf'):
        fig.savefig(args.batch/f'sequence_scaling.{extension}',dpi=200,facecolor='white')
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(11,6.8))
    fig.subplots_adjust(left=.1,right=.97,bottom=.18,top=.8)
    colors = {'correct':'#dff0e6','wrong':'#f9dddd','missing':'#edf0f5'}
    for row_index, r in enumerate(rows):
        for i, expected in enumerate(r['expected_sequence']):
            value = r['sequence'][i] if i < len(r['sequence']) else None
            kind = 'missing' if value is None else 'correct' if value == expected else 'wrong'
            ax.add_patch(Rectangle((i+.55,row_index-.4),.9,.8,facecolor=colors[kind],edgecolor='white',linewidth=1))
            ax.text(i+1,row_index,str(value) if value is not None else '—',ha='center',va='center',fontsize=11,color='#172b42')
    ax.set_xlim(.5,10.5)
    ax.set_ylim(len(rows)-.5,-.5)
    ax.set_xticks(list(range(1,11)))
    ax.set_yticks(list(range(len(rows))),[str(r['agents']) for r in rows])
    ax.set_xlabel('Submission position',labelpad=10)
    ax.set_ylabel('Agents in team',labelpad=10)
    ax.tick_params(length=0,pad=8)
    ax.spines[:].set_visible(False)
    fig.text(.1,.925,'What each team submitted',fontsize=24,weight='bold',color='#172b42')
    fig.text(.1,.865,'Cells show actual numbers in arrival order; color marks their exact sorted positions.',fontsize=11,color='#52657b')
    fig.legend(handles=[Patch(facecolor=colors[k],label=label) for k,label in
                        [('correct','Correct position'),('wrong','Wrong position'),('missing','Not submitted')]],
               loc='lower left',bbox_to_anchor=(.09,.015),ncol=3,frameon=False)
    for extension in ('png','svg','pdf'):
        fig.savefig(args.batch/f'submission_positions.{extension}',dpi=200,facecolor='white')
    plt.close(fig)
    print(args.batch/'sequence_scaling.png')


if __name__ == '__main__':
    main()
