import unittest
import numpy as np
from compare_profiles import aggregate,fit_candidate,diagnostic

class CandidateStudyTests(unittest.TestCase):
    def test_identity_reference_recovers_identity(self):
        s=(np.linspace(.05,.95,19),[.3]*6)
        model=fit_candidate([s],[s],2,1,.25,(.85,1.2))
        np.testing.assert_allclose(model[0],[0,0],atol=1e-12)
        np.testing.assert_allclose(model[1],[1]*6,atol=1e-12)
        self.assertAlmostEqual(diagnostic([s],[s],model),0)
    def test_missing_hues_fall_back_and_bounds_hold(self):
        s=(np.linspace(.05,.95,19),[None,.1,.9,None,.2,.8])
        t=(s[0],[None,.9,.1,None,.8,.1])
        model=fit_candidate([s],[t],2,1,.25,(.85,1.2))
        self.assertEqual(model[1][0],1)
        self.assertTrue(all(.85<=x<=1.2 for x in model[1]))
        self.assertIsNone(aggregate([s,t])[1][0])
