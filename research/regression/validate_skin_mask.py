"""Inspect a Digi MaskStudy capture without modifying the captured files.

Example:
  python validate_skin_mask.py output/device-mask-study-latest/<capture-id> \
    --output output/mask-validation/<capture-id>

The optional --ground-truth image must be an upright, full-resolution binary
skin annotation. Without one, coverage checks are diagnostics, not accuracy.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


def analyze(capture: Path, output: Path, ground_truth: Path | None = None) -> dict:
    capture = Path(capture)
    output = Path(output)
    metadata = json.loads((capture / "capture.json").read_text())
    with Image.open(capture / "original.jpg") as file:
        original_orientation = file.getexif().get(274, 1)
        photo = ImageOps.exif_transpose(file).convert("RGB")
    result = {
        "capture_id": capture.name,
        "status": "unknown",
        "photo_size_upright": list(photo.size),
        "jpeg_exif_orientation": original_orientation,
        "capture_original_orientation": metadata.get("original_orientation"),
        "skin_supported": metadata.get("skin_supported"),
        "skin_delivered": metadata.get("skin_delivered"),
        "flash_fired": metadata.get("flash_fired"),
        "warnings": [],
    }
    if metadata.get("original_orientation") != original_orientation:
        result["warnings"].append("capture.json orientation differs from JPEG EXIF")

    skin_path = capture / "skin.png"
    if not skin_path.exists():
        result["status"] = "mask_missing"
        if metadata.get("skin_delivered"):
            result["warnings"].append("capture.json reports delivery but skin.png is absent")
        output.mkdir(parents=True, exist_ok=True)
        (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
        return result

    with Image.open(skin_path) as file:
        mask = file.convert("L")
    result["mask_size_upright"] = list(mask.size)
    if metadata.get("mask_orientation", 1) != 1:
        raise ValueError("Expected an upright skin.png (mask_orientation == 1)")
    if [metadata.get("mask_width"), metadata.get("mask_height")] != list(mask.size):
        result["warnings"].append("capture.json mask dimensions differ from skin.png")
    if not metadata.get("skin_delivered"):
        result["warnings"].append("skin.png exists but capture.json reports no delivery")

    photo_ratio = photo.width / photo.height
    mask_ratio = mask.width / mask.height
    if abs(photo_ratio - mask_ratio) > 0.01:
        result["status"] = "aspect_mismatch"
        result["warnings"].append("Mask and upright photo have different aspect ratios; no overlay made")
        output.mkdir(parents=True, exist_ok=True)
        (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
        return result

    mask = mask.resize(photo.size, Image.Resampling.BILINEAR)
    values = np.asarray(mask, dtype=np.uint8)
    selected = values >= 128
    height, width = selected.shape
    edge = max(1, round(min(width, height) * 0.05))
    border = np.zeros_like(selected)
    border[:edge, :] = True
    border[-edge:, :] = True
    border[:, :edge] = True
    border[:, -edge:] = True
    result["status"] = "mask_present"
    result["mask_metrics"] = {
        "selected_fraction_at_50_percent": round(float(selected.mean()), 5),
        "mean_confidence": round(float(values.mean() / 255), 5),
        "border_selected_fraction": round(float(selected[border].mean()), 5),
        "selected_pixel_count": int(selected.sum()),
        "evaluation_threshold": 128,
    }
    if selected.any():
        ys, xs = np.nonzero(selected)
        result["mask_metrics"]["selected_bbox_xyxy_upright"] = [
            int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        ]
    else:
        result["warnings"].append("Mask delivered but contains no selected pixels")

    # The red opacity tracks the matte confidence, so feathered edges remain visible.
    alpha = Image.fromarray((values.astype(np.float32) * 0.58).astype(np.uint8), "L")
    red = Image.new("RGBA", photo.size, (255, 35, 55, 0))
    red.putalpha(alpha)
    overlay = Image.alpha_composite(photo.convert("RGBA"), red)
    output.mkdir(parents=True, exist_ok=True)
    overlay.convert("RGB").save(output / "overlay.jpg", quality=92)
    mask.save(output / "mask_aligned.png")

    if ground_truth is not None:
        with Image.open(ground_truth) as file:
            truth_image = file.convert("L")
        if truth_image.size != photo.size:
            raise ValueError("Ground truth must have the upright full-resolution photo dimensions")
        truth = np.asarray(truth_image) >= 128
        intersection = int(np.count_nonzero(selected & truth))
        predicted = int(selected.sum())
        actual = int(truth.sum())
        union = int(np.count_nonzero(selected | truth))
        result["ground_truth_metrics"] = {
            "precision": round(intersection / predicted, 5) if predicted else None,
            "recall": round(intersection / actual, 5) if actual else None,
            "intersection_over_union": round(intersection / union, 5) if union else None,
            "false_positive_fraction_of_background": round(
                float(np.count_nonzero(selected & ~truth) / np.count_nonzero(~truth)), 5
            ) if np.count_nonzero(~truth) else None,
        }
    else:
        result["warnings"].append("No labeled skin annotation: coverage and border metrics are not accuracy scores")
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="MaskStudy capture folder")
    parser.add_argument("--output", type=Path, required=True, help="Private output folder")
    parser.add_argument("--ground-truth", type=Path, help="Optional upright binary skin annotation")
    args = parser.parse_args()
    print(json.dumps(analyze(args.capture, args.output, args.ground_truth), indent=2))


if __name__ == "__main__":
    main()
