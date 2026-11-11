"""Offline, bounded rollback of Digi-added skin contrast/redness.

Not Canon calibration or learned skin-color matching. Uses paired pre-style and
styled pixels plus a conservative capture matte. No blur is applied to output
image detail: only the additive correction field is smoothed. Mask edges and
gamut clipping can still affect texture; inspect native-pixel comparisons.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageCms
from default_jpeg_study import full_image

WEIGHTS = np.array([.2126, .7152, .0722], dtype=np.float32)


def trusted_mask(raw):
    raw = np.asarray(raw, dtype=np.float32)
    if raw.ndim != 2 or not np.isfinite(raw).all() or raw.min() < 0 or raw.max() > 1:
        raise ValueError('Expected a finite 0..1 skin matte')
    # Reject faint guesses (including the reviewed rack object), slightly erode
    # the edge, then feather. This is a heuristic, not labeled-mask validation.
    image = Image.fromarray(np.uint8(raw >= .75) * 255, 'L')
    image = image.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1))
    return np.asarray(image, dtype=np.float32) / 255


def lowpass(field, radius=24):
    h, w = field.shape
    scale = min(1., 768 / max(h, w))
    size = (max(1, round(w*scale)), max(1, round(h*scale)))
    small = np.asarray(Image.fromarray(field.astype(np.float32)).resize(size, Image.Resampling.BILINEAR))
    sigma = max(1., radius*scale)
    reach = int(np.ceil(3*sigma))
    offsets = np.arange(-reach, reach+1)
    kernel = np.exp(-.5*(offsets/sigma)**2); kernel /= kernel.sum()
    for axis in [0, 1]:
        pads = [(0,0), (0,0)]; pads[axis] = (reach,reach)
        padded = np.pad(small, pads, mode='reflect')
        blurred = np.zeros_like(small)
        for i, weight in enumerate(kernel):
            slices = [slice(None),slice(None)]; slices[axis] = slice(i,i+small.shape[axis])
            blurred += weight*padded[tuple(slices)]
        small = blurred
    return np.asarray(Image.fromarray(small).resize((w,h), Image.Resampling.BILINEAR))


def balance_skin(original, styled, mask, strength=.25, red_strength=.25):
    original = np.asarray(original, dtype=np.float32)
    styled = np.asarray(styled, dtype=np.float32)
    mask = np.asarray(mask, dtype=np.float32)
    if original.shape != styled.shape or styled.ndim != 3 or styled.shape[-1] != 3 or mask.shape != styled.shape[:2]:
        raise ValueError('Expected aligned original/styled RGB and mask')
    if not (0 <= strength <= .6 and 0 <= red_strength <= .6):
        raise ValueError('Strength must be bounded to 0..0.6')
    for array in [original, styled, mask]:
        if not np.isfinite(array).all() or array.min() < 0 or array.max() > 1:
            raise ValueError('Inputs must be finite and within 0..1')
    if not np.any(mask): return styled.copy()
    # Gamma-encoded luma is descriptive here, not linear light luminance.
    original_y, styled_y = original @ WEIGHTS, styled @ WEIGHTS
    tone = np.clip(strength * lowpass(original_y-styled_y), -.025, .025)
    # Relative red chroma distinguishes extra saturation from simple exposure.
    # A denominator floor keeps the correction bounded in near-black pixels.
    red_excess = lowpass((styled[...,0]-styled_y)/np.maximum(styled_y,.1)
                        - (original[...,0]-original_y)/np.maximum(original_y,.1))
    red = -np.clip(red_strength*np.maximum(red_excess, 0)*lowpass(styled_y)/(1-WEIGHTS[0]), 0, .025)
    # Change R-G while preserving luma for the chroma portion. B-G is retained.
    result = styled.copy()
    result[...,0] += mask*(tone + (1-WEIGHTS[0])*red)
    result[...,1] += mask*(tone - WEIGHTS[0]*red)
    result[...,2] += mask*(tone - WEIGHTS[0]*red)
    return np.clip(result, 0, 1)


def evaluate(study, manifest, output):
    study, output = Path(study), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = json.loads(Path(manifest).read_text())
    report = []
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    for row in rows:
        folder = study / row['id']
        if not (folder/'skin.png').exists(): continue
        metadata = json.loads((folder/'capture.json').read_text())
        if metadata.get('mask_orientation',1) != 1: raise ValueError('Mask must be upright')
        original = full_image(folder/'original.jpg')
        styled = full_image(folder/'styled.jpg')
        if original.size != styled.size: raise ValueError('Original/styled dimensions differ')
        raw = Image.open(folder/'skin.png').convert('L')
        if abs(raw.width/raw.height-original.width/original.height) > .01: raise ValueError('Mask aspect mismatch')
        trusted = trusted_mask(np.asarray(raw, dtype=np.float32)/255)
        mask = np.asarray(Image.fromarray(trusted).resize(original.size, Image.Resampling.BILINEAR))
        dest = output/folder.name; dest.mkdir(exist_ok=True)
        Image.fromarray(np.uint8(mask*255)).save(dest/'trusted-mask.png')
        src = np.asarray(original, dtype=np.float32)/255
        base = np.asarray(styled, dtype=np.float32)/255
        sheet = Image.new('RGB', (1600,580), '#222222'); draw = ImageDraw.Draw(sheet)
        for j, (name, im) in enumerate([('Original',original),('Current Digi',styled)]):
            thumb=im.copy();thumb.thumbnail((390,535));sheet.paste(thumb,(j*400,30));draw.text((j*400+8,8),name,fill='white')
        selected = mask > .9
        ys,xs = np.nonzero(selected)
        # Skin bounding box is for reproducible context crops, not face detection.
        box = None if not len(xs) else (int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1)
        record = {'capture_id': folder.name, 'date': row.get('date'), 'flash_fired': metadata.get('flash_fired'),
                  'algorithm':'skin-balance-v1-relative-red',
                  'source_sha256':{n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in ['original.jpg','styled.jpg','skin.png']},
                  'dimensions':original.size, 'skin_bbox':box, 'variants':{},
                  'limits':'Unlabeled mask; one subject/session; metrics are not G12 accuracy or texture recovery scores.'}
        for j,(name,tone,red) in enumerate([('gentle',.2,.25),('balanced',.35,.4)],start=2):
            result=balance_skin(src,base,mask,tone,red)
            im=Image.fromarray(np.uint8(np.round(result*255)))
            im.save(dest/f'{name}.png',icc_profile=icc)
            thumb=im.copy();thumb.thumbnail((390,535));sheet.paste(thumb,(j*400,30));draw.text((j*400+8,8),name,fill='white')
            change=result-base; ychange=change @ WEIGHTS
            actual_red=(result[...,0]-result[...,1])-(base[...,0]-base[...,1])
            interior=(mask[:-1,:-1]>.99)&(mask[1:,:-1]>.99)&(mask[:-1,1:]>.99)
            ybase=base@WEIGHTS; yresult=result@WEIGHTS
            energy=lambda y: .5*(np.abs(np.diff(y,axis=0)[:,:-1])[interior].mean()+np.abs(np.diff(y,axis=1)[:-1,:])[interior].mean()) if interior.any() else 0.
            gbase=energy(ybase)
            record['variants'][name]={'tone_strength':tone,'red_strength':red,
                'mean_skin_luma_change':float(ychange[selected].mean()) if selected.any() else 0.,
                'mean_skin_R_minus_G_change':float(actual_red[selected].mean()) if selected.any() else 0.,
                'max_background_change':float(np.abs(change[mask==0]).max()) if np.any(mask==0) else None,
                'interior_gradient_ratio':float(energy(yresult)/gbase) if gbase else None,
                'max_RGB_change':float(np.abs(change).max())}
            del result,change,ychange,actual_red,ybase,yresult
        sheet.save(dest/'comparison.jpg',quality=95)
        report.append(record)
        (output/'report.json').write_text(json.dumps(report,indent=2))
        print(folder.name, 'exported two full-resolution candidates', flush=True)
    return report

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',required=True);parser.add_argument('--manifest',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();evaluate(args.study,args.manifest,args.output)
