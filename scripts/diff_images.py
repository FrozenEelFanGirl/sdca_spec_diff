# Copyright (c) 2026 FrozenEelFanGirl & Senary
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

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


def diff_images(path1: str, path2: str, threshold: int = 30) -> tuple[float, float, Image.Image, np.ndarray]:
    """Compare two images pixel-by-pixel. Returns (diff_ratio, mean_distance, base_img, diff_array)."""
    img1 = Image.open(path1).convert('RGB')
    img2 = Image.open(path2).convert('RGB')

    # Resize both to a common size so pixels align 1:1.
    # Using the average dimensions avoids cropping either image and
    # prevents false-positive diffs caused by independent resize+ crop.
    h = round((img1.height + img2.height) / 2)
    w1 = round(img1.width * h / img1.height)
    w2 = round(img2.width * h / img2.height)
    w = round((w1 + w2) / 2)

    img1_r = img1.resize((w, h), Image.LANCZOS)
    img2_r = img2.resize((w, h), Image.LANCZOS)

    a1 = np.array(img1_r)
    a2 = np.array(img2_r)

    diff = np.sqrt(np.sum((a1.astype(float) - a2.astype(float)) ** 2, axis=2))
    diff_pixels = np.sum(diff > threshold)
    ratio = diff_pixels / diff.size * 100
    mean_dist = np.mean(diff)

    return ratio, mean_dist, img1_r, diff


def generate_diff_overlay(base_img: Image.Image, diff: np.ndarray, threshold: int, output_path: str) -> None:
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
