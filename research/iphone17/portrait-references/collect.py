"""Catalog review samples; camera EXIF does not establish an unedited training pair."""
import re,json,hashlib,time,urllib.request,urllib.error
from pathlib import Path
from PIL import Image
s=Path('/tmp/digi-iphone-review.html').read_text()
urls=list(dict.fromkeys(re.findall(r'https://9to5mac\.com/wp-content/uploads/sites/6/2025/09/IMG_[^\s\"<>]+\.jpeg',s)))
out=Path('output/iphone17-portrait-references');out.mkdir(parents=True,exist_ok=True)
rows=[];blocked=False
for u in urls:
    p=out/u.rsplit('/',1)[1]
    r=dict(source_page='https://9to5mac.com/2025/09/17/iphone-17-pro-review/',original_url=u,file=str(p),status='not_downloaded',training_eligible=False,rights='Copyrighted; training permission unestablished',processing='Reviewer states Standard style; web export and later editing unknown',human_subject='unreviewed',lighting='unknown')
    if not blocked:
        try:
            if not p.exists():
                with urllib.request.urlopen(u,timeout=20) as f:p.write_bytes(f.read())
                time.sleep(.3)
            with Image.open(p) as im:
                ex=im.getexif();sub=ex.get_ifd(34665)
                r.update(model=ex.get(272),lens=sub.get(42036),iso=sub.get(34855),flash=sub.get(37385),dimensions=list(im.size),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),software=ex.get(305))
                im.verify()
            r['status']='verified_camera' if r['model']=='iPhone 17 Pro' else 'camera_unverified'
        except Exception as e:
            r.update(status='failed',error=str(e))
            if isinstance(e,urllib.error.HTTPError) and e.code in (403,429):blocked=True
    rows.append(r)
Path('research/iphone17/portrait-references/manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
print('Records',len(rows),'EXIF verified',sum(r['status']=='verified_camera' for r in rows))
