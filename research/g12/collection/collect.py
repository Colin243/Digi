"""Collect only explicit original-JPEG links from saved public review pages."""
import hashlib, json, re, urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
ROOT=Path('research/g12/collection'); (ROOT/'files').mkdir(parents=True,exist_ok=True)
html=Path('output/dataset/dkamera.html').read_text()
urls=sorted(set('https://www.dkamera.de'+u for u in re.findall(r'[/]media/testberichte/canon/powershot-g12/6_beispielaufnahmen/bilder/1_jpg/\d+\.jpg',html)))
def item(url):
    path=ROOT/'files'/('dkamera-'+url.rsplit('/',1)[-1])
    try:
        old=Path('research/g12/references')/path.name
        if not path.exists():
            if old.exists():path.write_bytes(old.read_bytes())
            else:
                req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
                path.write_bytes(urllib.request.urlopen(req,timeout=30).read())
        with Image.open(path) as im:
            ex=im.getexif(); detail=ex.get_ifd(34665)
            def number(key):
                v=detail.get(key)
                return float(v) if v is not None else None
            model=ex.get(272)
            if model!='Canon PowerShot G12':raise ValueError('Unexpected model '+str(model))
            return {'file':str(path),'source_url':url,'publisher':'dkamera','camera_model':model,'dimensions':list(im.size), 'ISO':detail.get(34855), 'exposure_seconds':number(33434),'f_number':number(33437),'focal_length_mm':number(37386),'flash_exif':detail.get(37385),'white_balance_exif':detail.get(41987),'capture_time':detail.get(36867),'software':ex.get(305),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'provenance':'Original JPEG section; RAW-developed and resized crops excluded','usage':'local evaluation; no redistribution or app bundling; training permission unestablished','scene_label':None,'lighting_label':None}
    except Exception as e:return {'source_url':url,'error':str(e)}
with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(item,urls))
# Keep separately collected publishers and reviewed scene labels on repeat runs.
previous=json.loads((ROOT/'manifest.json').read_text()) if (ROOT/'manifest.json').exists() else []
by_url={r['source_url']:r for r in previous}
for row in rows:
    old=by_url.get(row['source_url'],{})
    for key in ('scene_label','lighting_label','scene_group','label_provenance','flash_fired'):
        if key in old:row[key]=old[key]
rows.extend(r for r in previous if r['source_url'] not in urls)
(ROOT/'manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
print('dkamera original links',len(urls),'total manifest records',len(rows))
for r in rows:
 if 'error' in r:print(r)
