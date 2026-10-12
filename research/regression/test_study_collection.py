import unittest
import numpy as np
from study_collection import checked_quantiles


class DecodeValidationTests(unittest.TestCase):
    def test_blank_and_invalid_decodes_are_rejected(self):
        for image in [np.zeros((8, 8, 3)), np.ones((8, 8, 3)), np.full((8, 8, 3), np.nan)]:
            with self.assertRaises(ValueError):
                checked_quantiles(image)

    def test_valid_ramp_retains_quantile_order(self):
        ramp = np.repeat(np.linspace(0, 1, 64)[:, None], 3, axis=1)
        q = checked_quantiles(ramp)
        self.assertEqual(len(q), 97)
        self.assertTrue(np.all(np.diff(q) >= 0))
        self.assertAlmostEqual(q[0], .02)
        self.assertAlmostEqual(q[-1], .98)
