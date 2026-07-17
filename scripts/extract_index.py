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
Build a master index of all sections, figures, and tables from an SDCA spec .docx.

Usage:
  python extract_index.py <docx_path> [--output index.json]

Outputs index.json mapping every section/figure/table number to its heading/caption.
Also maps TOC section numbers from parse_toc() and resolves bookmark references.
"""

import sys
import os
import re
import json
import zipfile
from lxml import etree

from common import (
    W, NS, TOC_STYLES, FIGURE_TITLE_STYLES, TABLE_TITLE_STYLES,
    parse_toc, build_style_map, para_to_markdown, parse_xml, section_file,
)


def build_index(docx_path):
    """Build a master index mapping section/figure/table numbers to their info."""
    with zipfile.ZipFile(docx_path) as z:
        doc_xml = z.read('word/document.xml')
        styles_xml = z.read('word/styles.xml')

    root = parse_xml(doc_xml)
    body = root.find(f'{{{W}}}body')

    num_to_heading, heading_to_num = parse_toc(doc_xml)

    index = {
        'sections': {},
        'figures': {},
        'tables': {},
    }

    for num, heading in num_to_heading.items():
        index['sections'][num] = {
            'heading': heading,
            'level': num.count('.'),
            'file': f'../sections/{section_file(num, heading)}',
        }

    # Also scan body paragraphs for headings not captured by the TOC
    style_map = build_style_map(styles_xml)

    def _normalize_heading(h):
        h = h.replace(r'\<', '<').replace(r'\>', '>').replace(r'\*', '*')
        h = re.sub(r'#\s+(\d)', r'#\1', h)
        h = re.sub(r'\s+', ' ', h)
        h = h.replace('–', '-').replace('—', '-').lower()
        h = re.sub(r'^[\dA-Z\.]+\s*', '', h).strip()
        return h

    toc_norm_set = {_normalize_heading(h) for h in num_to_heading.values()}

    for child in body:
        if child.tag != f'{{{W}}}p':
            continue

        pPr = child.find(f'{{{W}}}pPr')
        style_id = None
        if pPr is not None:
            pStyle = pPr.find(f'{{{W}}}pStyle')
            if pStyle is not None:
                style_id = pStyle.get(f'{{{W}}}val')

        if style_id in TOC_STYLES:
            continue

        lvl = style_map.get(style_id, {}).get('resolved_outline') if style_id else None
        if lvl is None:
            continue

        text = para_to_markdown(child).strip()
        if not text:
            continue

        # Skip if this heading text is already covered by a TOC entry
        if _normalize_heading(text) in toc_norm_set:
            continue

        # Only add headings with a recognizable section number
        # (e.g. "5.1", "A.3", "B.2.5").  Unnumbered deep headings
        # are not standalone sections.
        m = re.match(r'^([\d]+(?:\.[\d]+)*)\s', text)
        if not m:
            continue

        num = m.group(1)
        heading = re.sub(r'^[\dA-Z\.]+\s*', '', text).strip()

        if num not in index['sections']:
            index['sections'][num] = {
                'heading': heading,
                'level': lvl,
                'file': f'../sections/{section_file(num, heading)}',
            }

    # Scan for figure and table captions
    for child in body:
        if child.tag != f'{{{W}}}p':
            continue

        pPr = child.find(f'{{{W}}}pPr')
        style_id = None
        if pPr is not None:
            pStyle = pPr.find(f'{{{W}}}pStyle')
            if pStyle is not None:
                style_id = pStyle.get(f'{{{W}}}val')

        text = para_to_markdown(child)

        if style_id in FIGURE_TITLE_STYLES:
            m = re.match(r'Figure\s+(\d+)\s+(.+)', text)
            if m:
                index['figures'][m.group(1)] = {
                    'caption': m.group(2).strip(),
                    'file': f'../images/Figure{m.group(1)}.png',
                }

        elif style_id in TABLE_TITLE_STYLES:
            m = re.match(r'Table\s+(\d+)\s+(.+)', text)
            if m:
                index['tables'][m.group(1)] = {
                    'caption': m.group(2).strip(),
                    'file': f'../tables/Table{m.group(1)}.md',
                }

    return index


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == '--from-config':
        from config import load_config
        cfg = load_config()
        target = sys.argv[2] if len(sys.argv) >= 3 else 'base'
        ver = cfg.base if target == 'base' else cfg.comparison
        docx_path = str(ver.docx)
        output_path = str(ver.index_file)
    else:
        docx_path = sys.argv[1]
        output_path = 'doc/output/index/index.json'
        if len(sys.argv) >= 4 and sys.argv[2] == '--output':
            output_path = sys.argv[3]

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    index = build_index(docx_path)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    total_sections = len(index['sections'])
    total_figures = len(index['figures'])
    total_tables = len(index['tables'])
    print(f'Index written to {output_path}', file=sys.stderr)
    print(f'  Sections: {total_sections}', file=sys.stderr)
    print(f'  Figures:  {total_figures}', file=sys.stderr)
    print(f'  Tables:   {total_tables}', file=sys.stderr)


if __name__ == '__main__':
    main()
