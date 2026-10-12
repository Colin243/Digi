"""Experimental spatial protection for Classic's designed layer, not a Canon calibration.

Vision face rectangles use normalized bottom-left coordinates. Feathered ellipses
approximate face regions, not precise skin segmentation. No identity recognition.
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from design_look import look
from fit_tone import load_srgb

def face_mask(shape,faces):
 h,w=shape;y,x=np.mgrid[:h,:w];x=(x+.5)/w;y=(y+.5)/h
 mask=np.zeros(shape)
 for f in faces:
  if f.get('confidence',0)<.7 or f['width']<=0 or f['height']<=0:continue
  cx=f['x']+f['width']/2;cy=1-f['y']-f['height']/2
  radius=np.sqrt(((x-cx)/(f['width']*.70))**2+((y-cy)/(f['height']*.75))**2)
  t=np.clip((1-radius)/.4,0,1);mask=np.maximum(mask,t*t*(3-2*t))
 return mask

def portrait_look(x,base,faces):
 classic=look(x,base)
 mask=face_mask(x.shape[:2],faces)[...,None]
 if not mask.any():return classic
 # Preserve fitted color, reduce only the additional designed contrast/hue layer.
 gentler=look(x,base,strength=.25)
 return classic*(1-mask)+gentler*mask

def main():
 base=json.loads(Path('research/regression/profiles/g12-fitted-v1.json').read_text())
 rows=json.loads(Path('output/portrait-model/faces.json').read_text());report=[]
 for i,r in enumerate(rows):
  im,_=load_srgb(r['file']);x=np.asarray(im)/255;classic=look(x,base);candidate=portrait_look(x,base,r['faces'])
  board=Image.new('RGB',(1500,700),'#181919');d=ImageDraw.Draw(board)
  for j,(title,y) in enumerate([('Original',x),('Classic v2',classic),('Face-protected candidate',candidate)]):
   p=Image.fromarray(np.round(y*255).astype('uint8'));p.thumbnail((490,645));board.paste(p,(j*500,35));d.text((j*500+5,10),title,fill='white')
  board.save(f'output/portrait-model/comparison-{i}.jpg',quality=95)
  report.append(dict(file=r['file'],split=r['split'],faces=len(r['faces']),mean_absolute_change_from_classic=float(np.abs(candidate-classic).mean())))
 Path('output/portrait-model/report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report,indent=2))
if __name__=='__main__':main()
