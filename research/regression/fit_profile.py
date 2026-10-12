"""Constrained, unpaired iPhone17 main-rear aesthetic fit. Not camera calibration."""
import hashlib,json
from pathlib import Path
from collections import defaultdict
import numpy as np
from PIL import Image,ImageDraw,ImageCms
from fit_tone import load_srgb,tone,fit,apply

def linear(x): return np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)
def srgb(x): return np.where(x<=.0031308,12.92*x,1.055*np.maximum(x,0)**(1/2.4)-.055)
def hue_weights(x):
    h=np.arctan2(np.sqrt(3)*(x[...,1]-x[...,2]),2*x[...,0]-x[...,1]-x[...,2])
    w=np.maximum(0,np.cos(h[...,None]-np.arange(6)*np.pi/3))**8
    return w/np.maximum(w.sum(axis=-1,keepdims=True),1e-9)
def transform(x,coeff,saturation):
    y=apply(x,np.asarray(coeff))
    lum=tone(y);chroma=y-lum[...,None]
    amount=np.clip(np.ptp(y,axis=-1)/.12,0,1)*np.clip((1-lum)/.15,0,1)
    scale=1+(hue_weights(y)@np.asarray(saturation)-1)*amount
    chroma=chroma*scale[...,None]
    limit=np.ones_like(y)
    np.divide(1-lum[...,None],chroma,out=limit,where=chroma>1e-9)
    np.divide(-lum[...,None],chroma,out=limit,where=chroma< -1e-9)
    return np.clip(lum[...,None]+chroma*np.minimum(1,limit.min(axis=-1))[...,None],0,1)
def stats(path):
    im,_=load_srgb(path);x=np.asarray(im,dtype=float)[::3,::3]/255
    if np.ptp(x)<1/255: raise ValueError('Blank source')
    l=tone(x);q=np.quantile(l,np.linspace(.05,.95,19))
    sat=np.ptp(x,axis=-1)/np.maximum(x.max(axis=-1),1e-6)
    bins=hue_weights(x).argmax(axis=-1);good=(l>.15)&(l<.85)&(sat>.08)
    colors=[float(np.median(sat[good&(bins==i)])) if np.count_nonzero(good&(bins==i))>=50 else None for i in range(6)]
    return q,colors

def main():
    sources=json.loads(Path('output/iphone-samples/primary-rear.json').read_text())
    # Same bedroom/session as the supplied checks is excluded from fitting.
    sources=[r for r in sources if r['file']!='IMG_9703.JPG']
    refs=json.loads(Path('research/g12/collection/manifest.json').read_text())
    groups=defaultdict(list)
    for r in refs: groups[r['scene_group']].append(stats(r['file']))
    target_q=np.mean([np.mean([s[0] for s in group],axis=0) for group in groups.values()],axis=0)
    ss=[stats(r['analysis_file']) for r in sources]
    # Match contrast shape with a median anchor, not the overall brightness of unrelated scenes.
    xs=np.concatenate([s[0] for s in ss]);ys=np.concatenate([np.clip(target_q-target_q[9]+s[0][9],0,1) for s in ss])
    coeff=fit(xs,ys,5.0)*.65
    sat=[];coverage=[]
    for c in range(6):
        a=[s[1][c] for s in ss if s[1][c] is not None]
        b=[np.median([s[1][c] for s in group if s[1][c] is not None]) for group in groups.values() if any(s[1][c] is not None for s in group)]
        # Ridge toward identity, followed by conservative bounds; not measured Canon constants.
        av=np.median(a) if a else 0;bv=np.median(b) if b else av
        sat.append(float(np.clip((av*bv+.5)/(av*av+.5),.9,1.12)))
        coverage.append([len(a),len(b)])
    out=Path('ios/Digi');n=65
    b,g,r=np.meshgrid(np.linspace(0,1,n),np.linspace(0,1,n),np.linspace(0,1,n),indexing='ij')
    values=np.stack([r,g,b],axis=-1)
    rgb=linear(transform(srgb(values),coeff,sat));rgba=np.concatenate([rgb,np.ones((*rgb.shape[:-1],1))],axis=-1).astype('<f4')
    data=rgba.tobytes();(out/'G12-iPhone17Pro.cube.bin').write_bytes(data)
    profile={'version':1,'device':'iPhone18,1','lens':'main rear','dimension':n,'tone_coefficients':coeff.tolist(),'saturation_by_opponent_hue':sat,'hue_coverage_source_target_groups':coverage,'source_count':len(sources),'target_images':len(refs),'target_groups':len(groups),'cube_sha256':hashlib.sha256(data).hexdigest(),'status':'experimental unpaired aesthetic profile; not calibrated G12 accuracy','color_space':'linear sRGB cube; encoded-sRGB fit','constraints':{'tone_ridge':5,'tone_strength':.65,'saturation_ridge':.5,'saturation_bounds':[.9,1.12]},'held_out':['IMG_9707.JPG','IMG_9708.JPG'],'excluded_related_source':'IMG_9703.JPG'}
    (out/'G12-iPhone17Pro.json').write_text(json.dumps(profile,indent=2)+'\n')
    dest=Path('output/g12-profile');dest.mkdir(parents=True,exist_ok=True)
    icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    board=Image.new('RGB',(1200,980),'#171919');draw=ImageDraw.Draw(board)
    for row,name in enumerate(profile['held_out']):
        im,_=load_srgb(Path('/Users/colin/Downloads')/name);x=np.asarray(im,dtype=float)/255
        y=transform(x,coeff,sat);edited=Image.fromarray(np.round(y*255).astype('uint8'))
        edited.save(dest/(name[:-4]+'-candidate.jpg'),quality=96,icc_profile=icc)
        for col,img in enumerate([im,edited]):
            img=img.copy();img.thumbnail((580,440));board.paste(img,(col*600,row*490+35))
            draw.text((col*600+12,row*490+10),name+(' | Original' if col==0 else ' | Fitted candidate'),fill='white')
    board.save(dest/'comparison.jpg',quality=94,icc_profile=icc)
    print(json.dumps(profile,indent=2))
if __name__=='__main__': main()
