"""Offline lighting-stratified fitting with manually reviewed labels; no runtime classifier."""
import json
from pathlib import Path
from collections import defaultdict
import numpy as np
from PIL import Image,ImageDraw,ImageCms
from fit_profile import stats,transform
from compare_profiles import aggregate,fit_candidate,diagnostic
from fit_tone import load_srgb

def main():
    out=Path('output/lighting-samples')
    rows=json.loads((out/'labeled.json').read_text())
    train=[r for r in rows if r['split']=='train'];evaluation=[r for r in rows if r['split']=='evaluation']
    assert not {r['session_group'] for r in train}&{r['session_group'] for r in evaluation}
    refs=json.loads(Path('research/g12/collection/manifest.json').read_text())
    refs+= [r for r in json.loads(Path('research/g12/collection/commons-manifest.json').read_text()) if r.get('training_eligible',True)]
    # No source photos have flash fired: exclude flashed target examples from these branches.
    refs=[r for r in refs if not ((r.get('flash_exif') or 0)&1)]
    targets=defaultdict(lambda:defaultdict(list))
    for r in refs:
        light=r['lighting_label'];key='indoor' if light.startswith('indoor') else 'daylight' if ('outdoor' in light or 'daylight' in light) else None
        if key:targets[key][r['scene_group']].append(stats(r['file']))
    old=json.loads(Path('ios/Digi/G12-iPhone17Pro.json').read_text());baseline=(old['tone_coefficients'],old['saturation_by_opponent_hue'])
    report={'stress_count':sum(r['split']=='stress' for r in rows),'train_count':len(train),'evaluation_count':len(evaluation),'excluded_count':sum(r['split']=='excluded' for r in rows),'profiles':{},'evaluation':[],'limitations':['Manually labeled daylight/indoor fitting, not a trained automatic lighting detector.','Unpaired target-distribution diagnostics do not measure G12 accuracy.','Colored lighting and night scenes are retained for stress evaluation; no unsupported branch is fitted.','No flash-lit source examples were found.','Date-based source session split prevents same-day overlap, not all possible repeated-scene overlap.','Phone app/profile unchanged.']}
    models={}
    for light in ['daylight','indoor']:
        selected=[r for r in train if r['lighting_group']==light];ss=[stats(r['analysis_file']) for r in selected]
        tt=[aggregate(g) for g in targets[light].values()]
        if len(ss)<3 or len(tt)<3:continue
        m=fit_candidate(ss,tt,5,.65,.5,(.9,1.12));models[light]=m
        report['profiles'][light]={'tone_coefficients':m[0].tolist(),'saturation_by_opponent_hue':m[1],'training_sources':len(ss),'target_groups':len(tt)}
    icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    for i,r in enumerate(evaluation):
        light=r['lighting_group'];m=models.get(light,baseline);im,_=load_srgb(r['analysis_file']);x=np.asarray(im,dtype=float)/255
        board=Image.new('RGB',(1500,690),'#171919');d=ImageDraw.Draw(board)
        for col,(name,model) in enumerate([('Original',([0,0],[1]*6)),('Installed v1',baseline),('Lighting candidate',m)]):
            picture=Image.fromarray(np.round(transform(x,*model)*255).astype('uint8'));picture.thumbnail((485,640));board.paste(picture,(col*500,35));d.text((col*500+10,10),name,fill='white')
        board.save(out/f'evaluation-{i}.jpg',quality=95,icc_profile=icc)
        tt=[aggregate(g) for g in targets[light].values()];s=stats(r['analysis_file'])
        report['evaluation'].append({'file':r['file'],'lighting':light,'comparison':f'evaluation-{i}.jpg','installed_diagnostic':diagnostic([s],tt,baseline),'candidate_diagnostic':diagnostic([s],tt,m)})
    (out/'lighting-study.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
