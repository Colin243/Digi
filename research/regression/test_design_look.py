import json,unittest
from pathlib import Path
import numpy as np
from design_look import look
from fit_profile import transform

class ClassicLookTests(unittest.TestCase):
    def setUp(self):
        self.base=json.loads((Path(__file__).parent/'profiles/g12-fitted-v1.json').read_text())
    def test_zero_artistic_strength_matches_fitted_base(self):
        x=np.random.default_rng(4).random((1000,3))
        np.testing.assert_allclose(look(x,self.base,0),transform(x,self.base['tone_coefficients'],self.base['saturation_by_opponent_hue']),atol=1e-7)
    def test_neutrals_endpoints_and_monotonicity(self):
        x=np.repeat(np.linspace(0,1,4096)[:,None],3,axis=1);y=look(x,self.base)
        self.assertTrue((np.diff(y[:,0])>=0).all())
        np.testing.assert_allclose(y[:,0],y[:,2],atol=1e-7)
        np.testing.assert_allclose(y[[0,-1]],[[0,0,0],[1,1,1]],atol=1e-7)
    def test_finite_bounded_and_non_mutating(self):
        x=np.random.default_rng(7).random((10000,3));copy=x.copy();y=look(x,self.base)
        self.assertTrue(np.isfinite(y).all() and y.min()>=0 and y.max()<=1)
        np.testing.assert_array_equal(x,copy)
