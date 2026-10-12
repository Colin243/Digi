"""Bounded local reference acquisition. No automatic training admission."""
import re,json,hashlib,time,urllib.request,urllib.error
from pathlib import Path
from PIL import Image,ExifTags
page='https://www.photographyblog.com/reviews/canon_powershot_g12_review'
html=Path('/tmp/digi-g12-review.html').read_text()
urls=list(dict.fromkeys(re.findall(r'https://img\.photographyblog\.com/reviews/canon_powershot_g12/photos/canon_powershot_g12_\d+\.jpg',html)))
out=Path('output/g12-portrait-expansion');out.mkdir(parents=True,exist_ok=True)
rows=[];blocked=False
for url in urls:
    p=out/url.rsplit('/',1)[1]
    r=dict(source_page=page,original_url=url,file=str(p),publisher='Photography Blog',rights='Copyrighted; reuse/training permission not established',training_eligible=False,processing='Publisher states full-sized samples unaltered',human_subject='not yet visually reviewed',lighting='unknown',scene_group='unreviewed',status='pending')
    if blocked:
        r['status']='not_attempted_after_access_denial';rows.append(r);continue
    try:
        if not p.exists():
            with urllib.request.urlopen(url,timeout=25) as f:p.write_bytes(f.read())
            time.sleep(.4)
        with Image.open(p) as im:
            ex=im.getexif();sub=ex.get_ifd(34665)
            r.update(model=ex.get(272),dimensions=list(im.size),iso=sub.get(34855),flash=sub.get(37385),software=ex.get(305),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            im.verify()
        r['status']='verified_camera' if r['model']=='Canon PowerShot G12' else 'camera_unverified'
    except Exception as e:
        r['status']='failed';r['error']=str(e)
        rows.append(r)
        if isinstance(e,urllib.error.HTTPError) and e.code in (403,429):blocked=True
        continue
    rows.append(r)
Path('research/g12/portrait-expansion/manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
print('Records',len(rows),'verified',sum(r['status']=='verified_camera' for r in rows),flush=True)
