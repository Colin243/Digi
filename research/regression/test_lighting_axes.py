import unittest
from lighting_axes import classify

class LightingAxesTests(unittest.TestCase):
 def test_window_is_daylight_but_inside(self):
  r=classify('window-lit portrait',16)
  self.assertEqual(r['light_source'],'daylight')
  self.assertEqual(r['context'],'window_lit_interior')
  self.assertEqual(r['direction'],'unknown')
 def test_backlight_does_not_imply_outdoors(self):
  r=classify('backlit bedroom',None)
  self.assertEqual(r['direction'],'backlit')
  self.assertEqual(r['light_source'],'unknown')
  self.assertEqual(r['flash'],'unknown')
 def test_flash_is_bitfield(self):
  self.assertEqual(classify('',25)['flash'],'fired')
  self.assertEqual(classify('',24)['flash'],'not_fired')
 def test_indoor_does_not_imply_tungsten(self):
  self.assertEqual(classify('restaurant meal',16)['light_source'],'unknown')
 def test_mixed_is_separate(self):
  self.assertEqual(classify('warm interior with window',16)['light_source'],'mixed')
