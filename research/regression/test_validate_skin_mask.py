import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from validate_skin_mask import analyze


class ValidateSkinMaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / "capture"
        self.capture.mkdir()
        Image.new("RGB", (8, 6), "white").save(self.capture / "original.jpg")

    def write_metadata(self, delivered):
        (self.capture / "capture.json").write_text(json.dumps({
            "original_orientation": 1,
            "mask_orientation": 1,
            "mask_width": 4,
            "mask_height": 3,
            "skin_supported": True,
            "skin_delivered": delivered,
            "flash_fired": False,
        }))

    def test_missing_mask_is_explicit(self):
        self.write_metadata(False)
        result = analyze(self.capture, self.root / "output")
        self.assertEqual(result["status"], "mask_missing")
        self.assertTrue((self.root / "output/report.json").exists())
        self.assertFalse((self.root / "output/overlay.jpg").exists())

    def test_overlay_and_ground_truth_metrics(self):
        self.write_metadata(True)
        mask = Image.new("L", (4, 3), 0)
        for x in (0, 1):
            for y in range(3):
                mask.putpixel((x, y), 255)
        mask.save(self.capture / "skin.png")
        truth = mask.resize((8, 6), Image.Resampling.NEAREST)
        truth.save(self.root / "truth.png")
        result = analyze(self.capture, self.root / "output", self.root / "truth.png")
        self.assertEqual(result["status"], "mask_present")
        self.assertEqual(result["ground_truth_metrics"]["precision"], 1)
        self.assertEqual(result["ground_truth_metrics"]["recall"], 1)
        with Image.open(self.root / "output/overlay.jpg") as overlay:
            self.assertEqual(overlay.size, (8, 6))

    def test_aspect_mismatch_does_not_make_misleading_overlay(self):
        self.write_metadata(True)
        Image.new("L", (4, 4), 255).save(self.capture / "skin.png")
        result = analyze(self.capture, self.root / "output")
        self.assertEqual(result["status"], "aspect_mismatch")
        self.assertFalse((self.root / "output/overlay.jpg").exists())


if __name__ == "__main__":
    unittest.main()
