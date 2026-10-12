"""Conservative annotation migration, NOT an image lighting classifier.
Unknown axes remain unknown. Source captions are visual inference, not measured light.
"""
import json
from pathlib import Path

def classify(description, flash):
 text=description.lower()
 light='unknown'; context='unknown'; direction='unknown'
 if 'outdoor' in text or 'field portrait' in text or 'street portrait' in text: context='outdoors'
 if 'overcast' in text or 'field portrait' in text: light='daylight'
 if 'window-lit' in text: light='daylight'; context='window_lit_interior'
 if 'warm interior with window' in text: light='mixed'; context='window_lit_interior'
 if 'backlit' in text: direction='backlit'
 return dict(light_source=light,context=context,direction=direction,
             flash='unknown' if not isinstance(flash,int) else 'fired' if flash & 1 else 'not_fired',
             flash_role='unknown',label_status='provisional_caption_inference',
             flash_evidence='source_manifest_EXIF' if isinstance(flash,int) else 'missing',
             needs_visual_review=True)

if __name__=='__main__':
 rows=json.loads(Path('output/lighting-samples/labeled.json').read_text())
 result=[dict(file=r['file'],session_group=r['session_group'],split=r['split'],scene_description=r['scene_description'],axes=classify(r['scene_description'],r.get('Flash'))) for r in rows if r['split']!='excluded']
 out=Path('output/lighting-axes');out.mkdir(parents=True,exist_ok=True)
 (out/'annotations.json').write_text(json.dumps(result,indent=2)+'\n')
 print('Wrote',len(result),'provisional annotations; original labels unchanged')
