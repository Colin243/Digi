import unittest
import numpy as np
from fit_profile import transform, srgb, linear

class ProfileTests(unittest.TestCase):
    def test_identity_and_transfer_roundtrip(self):
        x=np.random.default_rng(14).random((100,3))
        np.testing.assert_allclose(srgb(linear(x)),x,atol=1e-7)
        np.testing.assert_allclose(transform(x,[0,0],np.ones(6)),x,atol=1e-7)
    def test_neutral_ramp_and_gamut(self):
        ramp=np.repeat(np.linspace(0,1,256)[:,None],3,axis=1)
        y=transform(ramp,[.2,-.3],np.full(6,1.12))
        np.testing.assert_allclose(y[:,0],y[:,1],atol=1e-7)
        self.assertTrue((np.diff(y[:,0])>=0).all())
        x=np.random.default_rng(2).random((1000,3));old=x.copy()
        z=transform(x,[.2,-.3],np.full(6,1.12))
        self.assertTrue(np.isfinite(z).all() and z.min()>=0 and z.max()<=1)
        np.testing.assert_array_equal(x,old)
