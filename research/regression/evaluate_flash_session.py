"""Describe supplied flash pairs without treating face boxes as skin masks."""
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

root = Path('output/flash-texture-session')
rows = json.loads((root / 'report.json').read_text())
board = Image.new('RGB', (1200, 960), '#f1f0ec')
draw = ImageDraw.Draw(board)
results = []
for index, row in enumerate(rows):
    stem = row['stem']
    original = Image.open(row['input'])
    exif = original.getexif().get_ifd(34665)
    record = dict(file=stem, width=row['width'], height=row['height'],
                  flash_fired=row['flash_fired'], iso=exif.get(34855),
                  skin_matte_present=row['skin_matte_present'],
                  light_source='artificial ambient + flash' if row['flash_fired'] else 'artificial ambient',
                  context='indoor', session='warm-room-9767-9770',
                  role='portrait' if row['faces'] else 'no-person negative example',
                  label_provenance='Flash/ISO from EXIF; scene context from visual inspection',
                  directions='Overhead/rear ambient; frontal flash when fired',
                  calibration_eligible=False,
                  reason='Already rendered, no aligned pre-style source or skin mask; no matched G12 target')
    if row['faces']:
        f = row['faces'][0]
        w,h = original.size
        box = (int(f['x']*w), int((1-f['y']-f['height'])*h),
               int((f['x']+f['width'])*w), int((1-f['y'])*h))
        arr = np.asarray(original.convert('RGB').crop(box), dtype=np.float32)
        record['face_box_statistics_not_skin_metrics'] = {
            'mean_rgb': arr.mean(axis=(0,1)).tolist(),
            'any_channel_ge250_percent': float((arr.max(axis=2)>=250).mean()*100),
            'all_channels_ge250_percent': float((arr.min(axis=2)>=250).mean()*100)}
        cx,cy = (box[0]+box[2])//2,(box[1]+box[3])//2
        crop = (cx-200,cy-200,cx+200,cy+200)
        for j,name in enumerate(['baseline','chroma','combined']):
            im=Image.open(root/f'{stem}-{name}.png').convert('RGB')
            assert im.size == (3024,4032)
            board.paste(im.crop(crop),(j*400,index*480+50))
            draw.text((j*400+8,index*480+14),f'{stem} | {name} | 100% detail',fill='black')
        record['finishing_checks']={}
        base=np.asarray(Image.open(root/f'{stem}-baseline.png').convert('RGB'),dtype=np.float32)
        for name in ['chroma','highlights','combined']:
            out=np.asarray(Image.open(root/f'{stem}-{name}.png').convert('RGB'),dtype=np.float32)
            record['finishing_checks'][name]={'mean_absolute_rgb_change':float(np.abs(out-base).mean())}
    results.append(record)
board.save(root/'flash-portrait-detail.jpg',quality=96)
(root/'session.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
