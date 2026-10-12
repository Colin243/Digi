"""Bounded, alphabetically stratified Commons collection with explicit attribution/license provenance."""
import json,urllib.request,urllib.parse,time,hashlib,re
from pathlib import Path
from collections import Counter
from PIL import Image
ROOT=Path('research/g12/collection');OUT=Path('output/g12-v2');OUT.mkdir(parents=True,exist_ok=True)
def request(params):
 url='https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(dict(action='query',format='json',**params))
 return json.loads(urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'DigiPersonalResearch/0.2 (local camera color study)'}),timeout=30).read())
previous=json.loads((ROOT/'commons-manifest.json').read_text()) if (ROOT/'commons-manifest.json').exists() else []
rows={};errors=[]
for year in ["A","D","G","J","M","P","S","V"]:
 try:
  data=request(dict(generator='categorymembers',gcmtitle='Category:Taken_with_Canon_PowerShot_G12',gcmtype='file',gcmsort='sortkey',gcmdir='asc',gcmstartsortkey=year,gcmlimit=35,prop='imageinfo',iiprop='url|extmetadata|metadata'))
  (OUT/f'commons-{year}.json').write_text(json.dumps(data))
  for k,v in data.get('query',{}).get('pages',{}).items():rows[k]=v
 except urllib.error.HTTPError as e:
  errors.append(str(e))
  if e.code==429:break
 except Exception as e:errors.append(str(e))
 time.sleep(.3)
counts=Counter();manifest=[]
for key,row in rows.items():
 try:
  info=row.get('imageinfo',[{}])[0];ext=info.get('extmetadata',{});license=ext.get('LicenseShortName',{}).get('value','')
  if not any(x in license.lower() for x in ['cc by','cc0','public domain']):continue
  artist=ext.get('Artist',{}).get('value','unknown');artist=re.sub('<[^>]+>','',artist)
  if counts[artist]>=6:continue
  if not urllib.parse.urlparse(info.get('url','')).path.lower().endswith(('.jpg','.jpeg')):continue
  path=ROOT/'files'/f'commons-{key}.jpg'
  if not path.exists():path.write_bytes(urllib.request.urlopen(urllib.request.Request(info['url'],headers={'User-Agent':'DigiPersonalResearch/0.2'}),timeout=30).read())
  with Image.open(path) as im:
   ex=im.getexif();e=ex.get_ifd(34665);model=ex.get(272,'')
   if model.strip()!='Canon PowerShot G12':continue
   date=e.get(36867,'unknown');software=ex.get(305,'unknown')
   manifest.append(dict(file=str(path),source_url=info['url'],source_page=info['descriptionurl'],title=row['title'],artist=artist,license=license,license_url=ext.get('LicenseUrl',{}).get('value'),camera_model=model,ISO=e.get(34855),flash_exif=e.get(37385),software=software,capture_time=date,dimensions=list(im.size),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),scene_group=artist+'|'+date[:10],provenance='Commons original-file URL; EXIF verified; default-camera mode not established',target_class='edited_or_unknown',publisher='Wikimedia Commons',lighting_label='unreviewed'))
  counts[artist]+=1
  if len(manifest)>=60:break
 except urllib.error.HTTPError as e:
  errors.append(f'{key}: {e}')
  if e.code==429:break # Stop immediately; do not hammer the host or change endpoints.
 except Exception as e:errors.append(f'{key}: {e}')
 time.sleep(.15)
old_by_file={r['file']:r for r in previous}
for r in manifest:
 old=old_by_file.get(r['file'],{})
 for field in ['scene_label','lighting_label','label_provenance','training_eligible','exclusion_reason']:
  if field in old:r[field]=old[field]
seen={r['file'] for r in manifest}
manifest.extend(r for r in previous if r['file'] not in seen)
(ROOT/'commons-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(OUT/'collection-result.json').write_text(json.dumps(dict(candidates=len(rows),verified=len(manifest),authors=dict(counts),errors=errors),indent=2)+'\n')
print('Candidates',len(rows),'verified',len(manifest),'creators',len(counts),'errors',len(errors))
