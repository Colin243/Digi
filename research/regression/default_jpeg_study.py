"""Default-settings-only unpaired study. Never writes app assets. Not camera calibration."""
import json,hashlib,io
from pathlib import Path
from collections import defaultdict
import numpy as np
from PIL import Image,ImageCms,ImageOps,ImageDraw
from fit_tone import fit,apply,curve,tone
from fit_profile import stats
from design_look import look

OUT=Path('output/default-jpeg-study')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def full_image(p):
 with Image.open(p) as src:
  profile=src.info.get('icc_profile'); im=ImageOps.exif_transpose(src).convert('RGB')
  if profile:im=ImageCms.profileToProfile(im,ImageCms.ImageCmsProfile(io.BytesIO(profile)),ImageCms.createProfile('sRGB'),outputMode='RGB')
  return im

def estimate(sources,groups):
 target=np.mean([np.mean(v,axis=0) for v in groups.values()],axis=0)
 x=np.concatenate(sources); y=np.concatenate([np.clip(target-target[9]+q[9],0,1) for q in sources])
 return fit(x,y,10.0)*.5

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 original_assets={p.name:digest(p) for p in Path('ios/Digi').glob('G12-iPhone17Pro*')}
 refs=json.loads(Path('research/g12/collection/manifest.json').read_text())
 refs=[r for r in refs if 'My Colours Off' in r.get('provenance','')]
 for r in refs:
  assert digest(r['file'])==r['sha256']
  with Image.open(r['file']) as im:assert im.getexif().get(272)=='Canon PowerShot G12'
 sources=json.loads(Path('output/lighting-samples/labeled.json').read_text())
 sources=[r for r in sources if r['split'] in ['train','evaluation','stress'] and r['model']=='iPhone 17 Pro']
 source_paths={r['file']:next(p for p in [Path('output/lighting-samples/originals')/r['file'],Path('output/iphone-samples/originals')/r['file']] if p.exists()) for r in sources}
 held_sessions={r['session_group'] for r in sources if r['split'] in ['evaluation','stress']}
 report={'target':'G12 Large Fine JPEG, AWB, My Colours Off','status':'offline unpaired tone candidate; not validated camera response','references':refs,'profiles':{},'evaluations':[],'limitations':['One reference publisher; no default-JPEG human portraits or flash originals in verified subset.','Color gains remain identity: unmatched scene colors cannot establish a reliable hue transform.','iPhone source images are Apple Camera exports, not Digi capture-pipeline calibration.']}
 for light in ['daylight','indoor']:
  selected=[r for r in sources if r['split']=='train' and r['lighting_group']==light and r['session_group'] not in held_sessions]
  # Equal session weighting prevents a restaurant/session from dominating the source fit.
  sessions=defaultdict(list)
  for r in selected:sessions[r['session_group']].append(stats(source_paths[r['file']])[0])
  sq=[np.mean(v,axis=0) for v in sessions.values()]
  groups=defaultdict(list)
  for r in refs:
   if r['flash_fired']:continue
   if (light=='daylight')==r['lighting_label'].startswith('outdoor'):
    groups[r['scene_group']].append(stats(r['file'])[0])
  coeff=estimate(sq,groups)
  jack=[estimate(sq,{k:v for k,v in groups.items() if k!=held}).tolist() for held in groups] if len(groups)>1 else []
  report['profiles'][light]={'tone_coefficients':coeff.tolist(),'saturation':[1]*6,'source_sessions':len(sessions),'source_images':len(selected),'target_groups':len(groups),'target_images':sum(map(len,groups.values())),'leave_one_target_group_out_coefficients':jack}
  xx,yy=curve(coeff);assert np.isfinite(yy).all() and np.diff(yy).min()>=0
  gray=np.repeat(np.linspace(0,1,100)[:,None],3,axis=1);assert np.ptp(apply(gray,coeff),axis=1).max()<1e-12
 # Explicitly held-out, full-resolution renders; no fitting to these photos.
 selected=[r for r in sources if r['file'] in ['IMG_9077.JPG','IMG_8007.JPG','IMG_9703.JPG']]
 base=json.loads(Path('research/regression/profiles/g12-fitted-v1.json').read_text())
 icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
 for row in selected:
  path=source_paths[row['file']];im=full_image(path);coef=report['profiles'][row['lighting_group']]['tone_coefficients']
  candidate=Image.new('RGB',im.size);classic=Image.new('RGB',im.size)
  for top in range(0,im.height,128):
   box=(0,top,im.width,min(im.height,top+128));x=np.asarray(im.crop(box),dtype=float)/255
   candidate.paste(Image.fromarray(np.round(apply(x,coef)*255).astype('uint8')),(0,top))
   classic.paste(Image.fromarray(np.round(look(x,base)*255).astype('uint8')),(0,top))
  name=Path(row['file']).stem
  candidate.save(OUT/f'{name}-default-candidate.png',icc_profile=icc)
  classic.save(OUT/f'{name}-classic.png',icc_profile=icc)
  board=Image.new('RGB',(1500,720),'#191919');d=ImageDraw.Draw(board)
  for j,(label,img) in enumerate([('Original iPhone',im),('Current Classic',classic),('Default-JPEG tone study',candidate)]):
   thumb=img.copy();thumb.thumbnail((490,665));board.paste(thumb,(j*500,40));d.text((j*500+8,12),label,fill='white')
  board.save(OUT/f'{name}-comparison.jpg',quality=95,icc_profile=icc)
  # Detail crops retain one source pixel per output pixel.
  if name=='IMG_9077':
   f=json.loads(Path('output/portrait-model/faces.json').read_text())[2]['faces'][0]
   cx=int((f['x']+f['width']/2)*im.width);cy=int((1-f['y']-f['height']/2)*im.height)
   box=(cx-220,cy-220,cx+220,cy+220);detail=Image.new('RGB',(1320,475),'#191919');dd=ImageDraw.Draw(detail)
   for j,(label,img) in enumerate([('Original',im),('Classic',classic),('Default candidate',candidate)]):detail.paste(img.crop(box),(j*440,35));dd.text((j*440+5,10),label,fill='white')
   detail.save(OUT/'portrait-detail.png',icc_profile=icc)
  report['evaluations'].append({'source':str(path),'sha256':digest(path),'split':row['split'],'lighting':row['lighting_group'],'dimensions':list(im.size),'candidate':str(OUT/f'{name}-default-candidate.png')})
  print('Rendered',name,im.size,flush=True)
 assert original_assets=={p.name:digest(p) for p in Path('ios/Digi').glob('G12-iPhone17Pro*')}
 (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report['profiles'],indent=2))
if __name__=='__main__':main()
