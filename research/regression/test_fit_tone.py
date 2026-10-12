import unittest
import numpy as np
from fit_tone import fit, curve, apply

class ToneRegressionTests(unittest.TestCase):
    def test_identity_targets_recover_identity(self):
        x = np.linspace(.02, .98, 97)
        np.testing.assert_allclose(fit(x, x, 1), [0, 0], atol=1e-12)

    def test_known_basis_coefficients_are_recovered_without_penalty(self):
        from fit_tone import design
        x = np.linspace(.02, .98, 97)
        expected = np.array([.07, -.12])
        np.testing.assert_allclose(fit(x, x + design(x) @ expected, 0), expected, atol=1e-12)

    def test_extreme_coefficients_stay_monotonic_and_bounded(self):
        for coefficients in [[0, 0], [50, -50], [-50, 50], [.028, .265]]:
            x, y = curve(coefficients)
            self.assertEqual(y[0], 0)
            self.assertEqual(y[-1], 1)
            self.assertTrue(np.all(np.diff(y) >= 0))
            self.assertLessEqual(float(np.max(abs(y - x))), .080001)

    def test_output_is_finite_in_gamut_and_does_not_mutate_input(self):
        rgb = np.random.default_rng(8).random((20, 30, 3))
        copy = rgb.copy()
        output = apply(rgb, [4, -4])
        self.assertTrue(np.isfinite(output).all())
        self.assertGreaterEqual(output.min(), 0)
        self.assertLessEqual(output.max(), 1)
        np.testing.assert_array_equal(rgb, copy)

    def test_neutral_ramp_remains_neutral(self):
        rgb = np.repeat(np.linspace(0, 1, 256)[:, None], 3, axis=1)
        result = apply(rgb, [.028, .265])
        np.testing.assert_allclose(result[:, 0], result[:, 1], atol=1e-12)
        np.testing.assert_allclose(result[:, 1], result[:, 2], atol=1e-12)

if __name__ == '__main__': unittest.main()
