"""Creator-held-out unpaired candidate study. Reports style-distribution loss, NOT fidelity."""
import json,hashlib
from pathlib import Path
from collections import defaultdict
import numpy as np
from PIL import Image,ImageDraw,ImageCms
from fit_profile import stats,transform
from fit_tone import fit,load_srgb


def fit_candidate(source_stats, target_stats, ridge, strength, color_ridge, bounds):
    q=np.mean([t[0] for t in target_stats],axis=0)
    x=np.concatenate([s[0] for s in source_stats])
    y=np.concatenate([np.clip(q-q[9]+s[0][9],0,1) for s in source_stats])
    coeff=fit(x,y,ridge)*strength
    colors=[]
    for c in range(6):
        a=[s[1][c] for s in source_stats if s[1][c] is not None]
        b=[s[1][c] for s in target_stats if s[1][c] is not None]
        av=np.median(a) if a else 0;bv=np.median(b) if b else av
        colors.append(float(np.clip((av*bv+color_ridge)/(av*av+color_ridge),*bounds)))
    return coeff,colors


def aggregate(items):
    q=np.mean([s[0] for s in items],axis=0)
    colors=[float(np.median([s[1][c] for s in items if s[1][c] is not None])) if any(s[1][c] is not None for s in items) else None for c in range(6)]
    return q,colors


def diagnostic(source,targets,model):
    coeff,colors=model;loss=[]
    # Tone quantiles transform exactly under monotonic, luminance-preserving mapping.
    # Chroma term is a feature-space surrogate; gamut and hue blending are not modeled here.
    for s in source:
        rgb=np.repeat(s[0][:,None],3,axis=1);q=transform(rgb,coeff,colors)[:,0]
        tone_loss=np.mean([np.mean(np.abs((q-q[9])-(t[0]-t[0][9]))) for t in targets])
        color=[]
        for t in targets:
            for c in range(6):
                if s[1][c] is not None and t[1][c] is not None:color.append(abs(s[1][c]*colors[c]-t[1][c]))
        loss.append(float(tone_loss+.2*np.mean(color)))
    return float(np.mean(loss))


def main():
    dest=Path('output/g12-v2');dest.mkdir(exist_ok=True)
    sources=[r for r in json.loads(Path('output/iphone-samples/primary-rear.json').read_text()) if r['file']!='IMG_9703.JPG']
    source_stats=[stats(r['analysis_file']) for r in sources]
    rows=json.loads(Path('research/g12/collection/commons-manifest.json').read_text())
    rows=[r for r in rows if r.get('training_eligible',True)]
    external_creators={r['artist'] for r in rows}
    if len(rows)<3:raise ValueError('Insufficient external contributors')
    rows += json.loads(Path('research/g12/collection/manifest.json').read_text())
    groups=defaultdict(list)
    for r in rows:groups[r.get('artist',r['publisher'])].append(stats(r['file']))
    if len(groups)<3:raise ValueError('Insufficient independent creators')
    creators=list(groups);target=[aggregate(groups[k]) for k in creators]
    old=json.loads(Path('ios/Digi/G12-iPhone17Pro.json').read_text())
    configs={'restrained':(5,.65,.5,(.9,1.12)),'balanced':(2,1,.25,(.85,1.2)),'expressive':(.5,1,.1,(.8,1.3))}
    scores={k:[] for k in ['identity','installed_v1',*configs]}
    for held in range(len(target)):
        if creators[held] not in external_creators:continue # v1 already saw the review publishers.
        train=[t for i,t in enumerate(target) if i!=held]
        models={'identity':([0,0],[1]*6),'installed_v1':(old['tone_coefficients'],old['saturation_by_opponent_hue'])}
        models.update({k:fit_candidate(source_stats,train,*v) for k,v in configs.items()})
        for k,v in models.items():scores[k].append(diagnostic(source_stats,[target[held]],v))
    candidates={k:fit_candidate(source_stats,target,*v) for k,v in configs.items()}
    result={'held_out_creator_folds':len(external_creators),'source_count':len(sources),'target_count':len(rows),'creator_or_publisher_groups':creators,'scores':{k:{'mean':float(np.mean(v)),'folds':v} for k,v in scores.items()},'candidates':{k:{'tone_coefficients':v[0].tolist(),'saturation_by_opponent_hue':v[1]} for k,v in candidates.items()},'limitations':['Held-out creators, not paired-camera truth or held-out iPhone source sessions.','Loss is centered-tone error plus 0.2 times a saturation-feature surrogate. Lower does not prove a better G12 imitation.','Commons originals may be edited. They are not labeled default-camera ground truth.','All candidates are research outputs; installed profile is unchanged.']}
    (dest/'candidate-study.json').write_text(json.dumps(result,indent=2)+'\n')
    # Holdout bedroom and a separate colorful source for qualitative comparison.
    samples=[('/Users/colin/Downloads/IMG_9708.JPG','New Digi capture'),(sources[1]['analysis_file'],'Colored lighting (training source)')]
    for j,(path,label) in enumerate(samples):
        im,_=load_srgb(path);x=np.asarray(im,dtype=float)/255
        models={'Original':([0,0],[1]*6),'Installed v1':(old['tone_coefficients'],old['saturation_by_opponent_hue']),**candidates}
        board=Image.new('RGB',(1500,780),'#161818');d=ImageDraw.Draw(board)
        for i,(name,m) in enumerate(models.items()):
            rendered=Image.fromarray(np.round(transform(x,*m)*255).astype('uint8'));rendered.thumbnail((480,345))
            left=i%3*500;top=i//3*390
            board.paste(rendered,(left,top+35));d.text((left+10,top+10),name,fill='white')
        board.save(dest/f'candidates-{j+1}.jpg',quality=95,icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    print(json.dumps({k:v['mean'] for k,v in result['scores'].items()},indent=2))
if __name__=='__main__':main()
