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
Extract a single figure from an SDCA specification .docx as PNG.

Usage:
  python extract_figure.py <docx_path> <figure_number> [--output-dir DIR]

Example:
  python -X utf8 scripts/extract_figure.py <docx_path> 24
  → <output_dir>/images/Figure24.png  (579x235)
  → stdout: Figure24.png|Figure 24 Function Diagram Key: Guidance for Readers
"""
import sys
import os
import io
import re
import zipfile
from lxml import etree
from PIL import Image

from common import W, R, VML, parse_rels

R_NS = R  # alias for backward compatibility with inline blip lookups


def extract_figure(docx_path, figure_num, output_dir='doc/output/images'):
    """Extract a figure by number from a docx. Returns (filename, caption) or (None, None)."""
    os.makedirs(output_dir, exist_ok=True)

    with zipfile.ZipFile(docx_path) as z:
        with z.open('word/document.xml') as f:
            tree = etree.parse(f)

        root = tree.getroot()
        body = root.find(f'{{{W}}}body')

        rels_map = parse_rels(z)

        for p in body:
            if p.tag != f'{{{W}}}p':
                continue
            pPr = p.find(f'{{{W}}}pPr')
            style = ''
            if pPr is not None:
                ps = pPr.find(f'{{{W}}}pStyle')
                if ps is not None:
                    style = ps.get(f'{{{W}}}val')
            if style != 'FigureTitle':
                continue

            texts = [t.text or '' for t in p.findall(f'.//{{{W}}}t')]
            text = ''.join(texts).strip()
            m = re.match(rf'Figure\s+{figure_num}\s+(.+)', text)
            if not m:
                continue

            caption = text
            # Search backwards for the image/object in preceding paragraphs.
            # Look up to 20 paragraphs for the associated image
            # (safe upper bound; spec documents keep images and captions close together).
            prev = p.getprevious()
            for _ in range(20):
                if prev is None:
                    break
                if prev.tag == f'{{{W}}}p':
                    # OLE object (Visio)
                    for obj in prev.findall(f'.//{{{W}}}object'):
                        for imd in obj.findall(f'.//{{{VML}}}imagedata'):
                            rid = imd.get(f'{{{R_NS}}}id')
                            target = rels_map.get(rid)
                            if target:
                                img_data = z.read('word/' + target)
                                img = Image.open(io.BytesIO(img_data))
                                filename = f'Figure{figure_num}.png'
                                img.save(os.path.join(output_dir, filename), 'PNG')
                                return filename, caption

                    # Regular drawing
                    for draw in prev.findall(f'.//{{{W}}}drawing'):
                        for blip in draw.findall(f'.//{{{R_NS}}}blip'):
                            embed = blip.get(f'{{{R_NS}}}embed')
                            target = rels_map.get(embed)
                            if target:
                                img_data = z.read('word/' + target)
                                img = Image.open(io.BytesIO(img_data))
                                filename = f'Figure{figure_num}.png'
                                img.save(os.path.join(output_dir, filename), 'PNG')
                                return filename, caption
                prev = prev.getprevious()
            return None, None

        return None, None


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    docx_path = sys.argv[1]
    figure_num = sys.argv[2]
    output_dir = 'doc/output/images'

    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == '--output-dir' and i + 1 < len(sys.argv):
            output_dir = sys.argv[i + 1]
            i += 2
        else:
            print(f'Unknown arg: {sys.argv[i]}', file=sys.stderr)
            sys.exit(1)

    filename, caption = extract_figure(docx_path, figure_num, output_dir)
    if filename:
        print(f'{filename}|{caption}')
    else:
        print(f'Figure {figure_num} not found', file=sys.stderr)
        sys.exit(1)
