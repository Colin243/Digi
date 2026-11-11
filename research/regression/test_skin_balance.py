import unittest
import numpy as np
from skin_balance import balance_skin, trusted_mask

class SkinBalanceTests(unittest.TestCase):
    def test_missing_selection_preserves_style_and_inputs(self):
        original = np.full((32, 32, 3), .4, dtype=np.float32)
        styled = original + np.array([.06, -.02, -.01], dtype=np.float32)
        before = styled.copy()
        result = balance_skin(original, styled, np.zeros((32, 32)))
        np.testing.assert_array_equal(result, styled)
        np.testing.assert_array_equal(styled, before)

    def test_changes_stay_within_mask(self):
        original = np.full((64, 64, 3), [.48, .35, .28], dtype=np.float32)
        styled = original + np.array([.07, -.01, -.02], dtype=np.float32)
        mask = np.zeros((64, 64), dtype=np.float32); mask[16:48, 16:48] = 1
        result = balance_skin(original, styled, mask)
        np.testing.assert_array_equal(result[mask == 0], styled[mask == 0])
        self.assertLess((result[32, 32, 0] - result[32, 32, 1]), (styled[32, 32, 0] - styled[32, 32, 1]))
        self.assertLessEqual(float(abs(result-styled).max()), .06)

    def test_natural_redness_is_not_normalized(self):
        original = np.full((32, 32, 3), [.6, .3, .25], dtype=np.float32)
        result = balance_skin(original, original.copy(), np.ones((32, 32)))
        np.testing.assert_allclose(result, original, atol=1e-6)

    def test_redness_relative_to_brightness_is_reduced(self):
        original = np.full((32,32,3), [.6,.4,.3], dtype=np.float32)
        styled = original - .08  # Same R-G, but greater relative chroma in darker skin.
        result = balance_skin(original, styled, np.ones((32,32)), strength=0)
        self.assertLess(float(result[16,16,0]-result[16,16,1]), float(styled[16,16,0]-styled[16,16,1])-.001)

    def test_shared_fine_texture_survives_constant_color_correction(self):
        fine = (np.indices((64, 64)).sum(axis=0) % 2) * .02
        original = np.full((64, 64, 3), [.5, .4, .35], dtype=np.float32) + fine[..., None]
        styled = original + np.array([.05, -.01, -.01])
        result = balance_skin(original, styled, np.ones((64, 64)))
        np.testing.assert_allclose(np.diff(result[30], axis=0), np.diff(styled[30], axis=0), atol=2e-6)

    def test_low_confidence_background_is_not_selected(self):
        raw = np.zeros((64, 64), dtype=np.float32); raw[8:48,8:40] = 1; raw[20:28,52:60] = .4
        mask = trusted_mask(raw)
        self.assertEqual(float(mask[24,56]), 0)
        self.assertGreater(float(mask[24,24]), .99)

    def test_invalid_shapes_and_values_rejected(self):
        x = np.full((8,8,3), .4)
        with self.assertRaises(ValueError): balance_skin(x, x, np.zeros((4,4)))
        with self.assertRaises(ValueError): balance_skin(x, x, np.full((8,8), np.nan))
        with self.assertRaises(ValueError): balance_skin(x, x, np.ones((8,8)), strength=2)
