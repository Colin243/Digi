import unittest,tempfile
from pathlib import Path
import numpy as np
from PIL import Image
from default_jpeg_study import full_image,estimate
from fit_tone import apply,curve

class DefaultJPEGTests(unittest.TestCase):
 def test_full_loader_preserves_resolution_and_bakes_orientation(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'sample.jpg';exif=Image.Exif();exif[274]=6
   Image.new('RGB',(1600,1200),(100,140,180)).save(p,exif=exif)
   result=full_image(p)
   self.assertEqual(result.size,(1200,1600))
 def test_tiled_transform_has_no_seams(self):
  x=np.random.default_rng(4).random((39,23,3));coeff=[.03,.08]
  entire=apply(x,coeff)
  tiled=np.concatenate([apply(x[i:i+8],coeff) for i in range(0,len(x),8)])
  np.testing.assert_allclose(entire,tiled,atol=1e-12)
 def test_identity_distribution_stays_identity(self):
  q=np.linspace(.05,.95,19)
  c=estimate([q,q],{'a':[q],'b':[q]})
  np.testing.assert_allclose(c,0,atol=1e-12)
  x,y=curve(c);self.assertTrue((np.diff(y)>=0).all())
