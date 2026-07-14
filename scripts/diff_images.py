"""
Pixel-diff two images (typically Figure PNGs from different spec versions).
Outputs: "<ratio>|<verdict>" where verdict is "unchanged" or "changed".

Usage:
  python diff_images.py <image1> <image2> [--diff-output DIFF.png] [--threshold N] [--verdict-threshold N]

  --threshold N        Pixel RGB distance to count as "different" (default: 30, range 0-255)
  --verdict-threshold N  Ratio % below which the image is considered "unchanged" (default: 2.0)
"""
import sys
import numpy as np
from PIL import Image

# Threshold below which images are considered unchanged
VERDICT_THRESHOLD = 2.0


def diff_images(path1, path2, threshold=30):
    """Compare two images pixel-by-pixel. Returns (diff_ratio, mean_distance, base_img, diff_array)."""
    img1 = Image.open(path1).convert('RGB')
    img2 = Image.open(path2).convert('RGB')

    # Resize to same height, compare at overlapping width
    h = min(img1.height, img2.height)
    w1 = int(img1.width * h / img1.height)
    w2 = int(img2.width * h / img2.height)

    img1_r = img1.resize((w1, h), Image.LANCZOS)
    img2_r = img2.resize((w2, h), Image.LANCZOS)

    w = min(w1, w2)
    img1_c = img1_r.crop((0, 0, w, h))
    img2_c = img2_r.crop((0, 0, w, h))

    a1 = np.array(img1_c)
    a2 = np.array(img2_c)

    diff = np.sqrt(np.sum((a1.astype(float) - a2.astype(float)) ** 2, axis=2))
    diff_pixels = np.sum(diff > threshold)
    ratio = diff_pixels / diff.size * 100
    mean_dist = np.mean(diff)

    return ratio, mean_dist, img1_c, diff


def generate_diff_overlay(base_img, diff, threshold, output_path):
    """Generate a diff overlay: red pixels where images differ."""
    base_arr = np.array(base_img)
    mask = diff > threshold
    base_arr[mask] = (255, 0, 0)
    diff_img = Image.fromarray(base_arr)
    blended = Image.blend(base_img, diff_img, 0.4)
    blended.save(output_path)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    path1 = sys.argv[1]
    path2 = sys.argv[2]
    diff_output = None
    threshold = 30
    verdict_threshold = VERDICT_THRESHOLD

    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == '--diff-output' and i + 1 < len(sys.argv):
            diff_output = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--threshold' and i + 1 < len(sys.argv):
            threshold = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == '--verdict-threshold' and i + 1 < len(sys.argv):
            verdict_threshold = float(sys.argv[i + 1])
            i += 2
        else:
            print(f'Unknown arg: {sys.argv[i]}', file=sys.stderr)
            sys.exit(1)

    ratio, mean_dist, base_img, diff = diff_images(path1, path2, threshold)
    verdict = 'unchanged' if ratio < verdict_threshold else 'changed'
    print(f'{ratio:.1f}|{verdict}')

    if diff_output:
        generate_diff_overlay(base_img, diff, threshold, diff_output)
        print(f'Diff overlay: {diff_output}', file=sys.stderr)
