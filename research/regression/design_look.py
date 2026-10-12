"""Reference-guided artistic layer over fitted v1. Not a newly calibrated camera model."""
import json,hashlib
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageCms
from fit_profile import transform,linear,srgb,hue_weights
from fit_tone import tone,apply,load_srgb

def look(x,base,strength=1):
    y=transform(x,base['tone_coefficients'],base['saturation_by_opponent_hue'])
    # Defined contrast response; endpoints preserved, no uniform warm cast.
    y=apply(y,[.025*strength,.85*strength])
    lum=tone(y);c=y-lum[...,None];w=hue_weights(y)
    gains=np.array([1.10,1.02,1.13,1.06,1.08,1.01])
    saturation=1+(w@gains-1)*strength
    # Hue-selective, luma-neutral channel offsets: cyan toward blue, yellow toward green.
    offsets=np.array([[.006,.001,-.004],[-.004,.006,-.006],[-.003,.003,0],[-.006,-.002,.010],[0,-.002,.004],[.002,0,0]])
    delta=w@offsets;delta-=tone(delta)[...,None]
    amount=np.clip(np.ptp(y,axis=-1)/.2,0,1)*np.clip((1-lum)/.18,0,1)
    c=c*saturation[...,None]+delta*amount[...,None]*strength
    limit=np.ones_like(c);np.divide(1-lum[...,None],c,out=limit,where=c>1e-9);np.divide(-lum[...,None],c,out=limit,where=c< -1e-9)
    return np.clip(lum[...,None]+c*np.minimum(1,limit.min(axis=-1))[...,None],0,1)

def main():
    out=Path('output/g12-v3');base=json.loads(Path('research/regression/profiles/g12-fitted-v1.json').read_text())
    samples=json.loads(Path('output/lighting-samples/labeled.json').read_text());selected=[r for r in samples if r['split']=='evaluation']
    for i,r in enumerate(selected):
        im,_=load_srgb(r['analysis_file']);x=np.asarray(im)/255;board=Image.new('RGB',(1500,700),'#181919');d=ImageDraw.Draw(board)
        for j,(name,y) in enumerate([('Original',x),('Installed v1',transform(x,base['tone_coefficients'],base['saturation_by_opponent_hue'])),('Classic candidate',look(x,base))]):
            p=Image.fromarray(np.round(y*255).astype('uint8'));p.thumbnail((485,640));board.paste(p,(j*500,40));d.text((j*500+8,12),name,fill='white')
        board.save(out/f'comparison-{i}.jpg',quality=95,icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    # Safety checks on dense neutral ramp and random colors, before packaging.
    ramp=np.repeat(np.linspace(0,1,4096)[:,None],3,axis=1);yr=look(ramp,base)
    assert np.min(np.diff(yr[:,0]))>=-1e-7
    assert np.max(np.ptp(yr,axis=-1))<1e-7
    random=np.random.default_rng(19).random((10000,3));z=look(random,base);assert np.isfinite(z).all() and z.min()>=0 and z.max()<=1
    n=65;b,g,r=np.meshgrid(np.linspace(0,1,n),np.linspace(0,1,n),np.linspace(0,1,n),indexing='ij');x=np.stack([r,g,b],axis=-1)
    rgb=linear(look(srgb(x),base));data=np.concatenate([rgb,np.ones((*rgb.shape[:-1],1))],axis=-1).astype('<f4').tobytes()
    (out/'candidate.cube.bin').write_bytes(data)
    meta=dict(base,version=2,status='G12-inspired Classic: fitted v1 plus explicit reference-guided artistic contrast/hue layer; not calibrated Canon output',cube_sha256=hashlib.sha256(data).hexdigest(),artistic_layer={'contrast_coefficients':[.025,.85],'selective_saturation':[1.10,1.02,1.13,1.06,1.08,1.01],'synthetic_grain':False})
    (out/'candidate.json').write_text(json.dumps(meta,indent=2)+'\n');print('Five comparison sheets and validated candidate cube generated.')
if __name__=='__main__':main()
