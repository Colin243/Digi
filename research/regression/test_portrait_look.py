import unittest,json
from pathlib import Path
import numpy as np
from portrait_look import portrait_look,face_mask
from design_look import look

class PortraitLookTests(unittest.TestCase):
 def setUp(self):
  self.base=json.loads((Path(__file__).parent/'profiles/g12-fitted-v1.json').read_text())
 def test_no_faces_exactly_preserves_classic(self):
  x=np.random.default_rng(1).random((32,32,3))
  np.testing.assert_array_equal(portrait_look(x,self.base,[]),look(x,self.base))
 def test_face_changes_are_local_and_finite(self):
  x=np.full((100,100,3),[.45,.30,.22]);faces=[dict(x=.4,y=.4,width=.2,height=.2,confidence=.99)]
  y=portrait_look(x,self.base,faces);classic=look(x,self.base)
  np.testing.assert_array_equal(y[0],classic[0]);self.assertGreater(abs(y[50,50]-classic[50,50]).max(),.001)
  self.assertTrue(np.isfinite(y).all() and y.min()>=0 and y.max()<=1)
 def test_bottom_origin_conversion_and_low_confidence(self):
  m=face_mask((100,100),[dict(x=.4,y=.1,width=.2,height=.2,confidence=.99)])
  self.assertGreater(m[80,50],.9);self.assertEqual(m[20,50],0)
  self.assertEqual(face_mask((100,100),[dict(x=.4,y=.1,width=.2,height=.2,confidence=.1)]).max(),0)
