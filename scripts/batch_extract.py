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
Batch extract all sections from an SDCA specification .docx file.
Single-pass: opens the docx once, writes each section to its own file.

Usage:
  python -X utf8 scripts/batch_extract.py <docx_path> --output-dir DIR [--index PATH]
"""

import sys
import os
import re
import json
import zipfile
from lxml import etree

from common import (
    W, A, R, NS, VML,
    TOC_STYLES, BULLET_STYLES, NUMBERED_STYLES, CODE_STYLES,
    NOTE_HEAD_STYLES, NOTE_BODY_STYLES, DEFINITION_STYLES,
    FIGURE_TITLE_STYLES, TABLE_TITLE_STYLES,
    build_style_map, parse_toc, parse_rels,
    para_to_markdown, get_list_indent, table_to_markdown,
    section_file, resolve_refs, render_output_to_markdown, sort_key,
)
from extract_section import (
    _extract_image_file, _find_image_in_paragraph, _peek_next_figure_title,
)


def batch_extract(docx_path, output_dir, index_path=None):
    sections_dir = os.path.join(output_dir, 'sections')
    images_dir = os.path.join(output_dir, 'images')
    tables_dir = os.path.join(output_dir, 'tables')
    os.makedirs(sections_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(tables_dir, exist_ok=True)

    z = zipfile.ZipFile(docx_path)
    styles_xml = z.read('word/styles.xml')
    style_map = build_style_map(styles_xml)
    doc_xml = z.read('word/document.xml')
    root = etree.fromstring(doc_xml)
    body = root.find(f'{{{W}}}body')

    rels_map = parse_rels(z)
    num_to_heading, heading_to_num = parse_toc(doc_xml)

    # Load index for cross-reference resolution
    index_data = None
    if index_path and os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)

    # First pass: find all heading elements and their positions in the body
    heading_positions = []  # (child_index, section_num, heading_text, level)
    body_children = list(body)
    for idx, child in enumerate(body_children):
        if child.tag != f'{{{W}}}p':
            continue
        pPr = child.find('w:pPr', NS)
        if pPr is None:
            continue
        pStyle = pPr.find('w:pStyle', NS)
        if pStyle is None:
            continue
        style_id = pStyle.get(f'{{{W}}}val')
        lvl = style_map.get(style_id, {}).get('resolved_outline')
        if lvl is None:
            continue
        text = para_to_markdown(child).strip()
        if not text:
            continue
        # Find section number for this heading
        h_norm = text.lower().replace('–', '-').replace('—', '-')
        h_norm = re.sub(r'^[\dA-Z\.]+\s*', '', h_norm).strip()
        section_num = None
        for num, heading in num_to_heading.items():
            nh = heading.lower().replace('–', '-').replace('—', '-')
            nh = re.sub(r'^[\dA-Z\.]+\s*', '', nh).strip()
            if nh == h_norm:
                section_num = num
                break
        if section_num:
            heading_positions.append((idx, section_num, text, lvl))

    # Build a lookup from section number to its heading position index
    section_to_pos = {}
    for pos_idx, (child_idx, section_num, heading_text, lvl) in enumerate(heading_positions):
        section_to_pos[section_num] = pos_idx

    # For each section in the TOC, determine the range of body children it covers
    extracted_count = 0
    all_section_nums = sorted(num_to_heading.keys(), key=sort_key)

    for section_num in all_section_nums:
        if section_num not in section_to_pos:
            continue

        pos_idx = section_to_pos[section_num]
        child_idx, heading_text, target_level = heading_positions[pos_idx][0], heading_positions[pos_idx][2], heading_positions[pos_idx][3]

        # Find end of this section: next heading at level <= target_level
        end_idx = len(body_children)
        for j in range(pos_idx + 1, len(heading_positions)):
            if heading_positions[j][3] <= target_level:
                end_idx = heading_positions[j][0]
                break

        # Extract content from child_idx to end_idx
        output = []
        num_counters = {}
        handled_elements = set()
        pending_caption = None
        tables_written = {}

        for i in range(child_idx, end_idx):
            child = body_children[i]

            if child.tag == f'{{{W}}}p':
                pPr = child.find('w:pPr', NS)
                style_id = None
                if pPr is not None:
                    pStyle = pPr.find('w:pStyle', NS)
                    if pStyle is not None:
                        style_id = pStyle.get(f'{{{W}}}val')

                if style_id in TOC_STYLES:
                    continue

                text = para_to_markdown(child).strip()

                lvl = style_map.get(style_id, {}).get('resolved_outline') if style_id else None

                if lvl is not None:
                    if not text:
                        continue
                    output.append(('heading', (lvl, text)))
                    continue

                # Check for images
                if rels_map:
                    img_filename = _find_image_in_paragraph(child, z, rels_map, images_dir)
                    if img_filename:
                        caption, caption_elem = _peek_next_figure_title(child)
                        if caption:
                            handled_elements.add(caption_elem)
                            m = re.match(r'Figure\s+(\d+)', caption)
                            if m:
                                new_name = f'Figure{m.group(1)}.png'
                                old_path = os.path.join(images_dir, img_filename)
                                new_path = os.path.join(images_dir, new_name)
                                if old_path != new_path:
                                    if os.path.exists(new_path):
                                        os.remove(new_path)
                                    os.rename(old_path, new_path)
                                img_filename = new_name
                            output.append(('image_with_caption', (img_filename, caption)))
                        else:
                            output.append(('image_only', img_filename))
                        continue

                if not text:
                    continue

                if child in handled_elements:
                    continue

                if style_id in BULLET_STYLES:
                    indent = get_list_indent(style_id)
                    num_counters = {k: v for k, v in num_counters.items() if k <= indent}
                    output.append(('bullet', (indent, text)))
                elif style_id in NUMBERED_STYLES:
                    indent = get_list_indent(style_id)
                    num_counters = {k: v for k, v in num_counters.items() if k <= indent}
                    num_counters[indent] = num_counters.get(indent, 0) + 1
                    output.append(('numbered', (indent, num_counters[indent], text)))
                elif style_id in CODE_STYLES:
                    output.append(('code', text))
                elif style_id in NOTE_HEAD_STYLES:
                    output.append(('note_head', text))
                elif style_id in NOTE_BODY_STYLES:
                    output.append(('note_body', text))
                elif style_id in DEFINITION_STYLES:
                    output.append(('definition', text))
                elif style_id in FIGURE_TITLE_STYLES:
                    output.append(('figure_title', text))
                elif style_id in TABLE_TITLE_STYLES:
                    m = re.match(r'Table\s+(\d+)\s+(.+)', text)
                    if m:
                        pending_caption = (text, m.group(1))
                    else:
                        output.append(('table_title', text))
                else:
                    num_counters.clear()
                    output.append(('body', text))

            elif child.tag == f'{{{W}}}tbl':
                md_table = table_to_markdown(child)
                if md_table and pending_caption:
                    caption_text, table_num = pending_caption
                    pending_caption = None
                    table_md = f'**{caption_text}**\n\n{md_table}\n'
                    tables_written[table_num] = table_md
                    output.append(('table_with_caption', (md_table, caption_text, table_num)))
                elif md_table:
                    output.append(('table', md_table))

        if pending_caption:
            output.append(('table_title', pending_caption[0]))

        text = render_output_to_markdown(output)

        # Resolve cross-references
        if index_data:
            text = resolve_refs(text, index_data)

        # Write section file
        filename = section_file(section_num, heading_text)
        filepath = os.path.join(sections_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(text)

        # Write standalone table files
        for table_num, table_md in tables_written.items():
            table_path = os.path.join(tables_dir, f'Table{table_num}.md')
            with open(table_path, 'w', encoding='utf-8') as f:
                f.write(table_md)

        extracted_count += 1

    return extracted_count


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    docx_path = sys.argv[1]
    output_dir = 'doc/output'
    index_path = os.path.join(output_dir, 'index', 'index.json')
    if not os.path.exists(index_path):
        index_path = None

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--output-dir' and i + 1 < len(sys.argv):
            output_dir = sys.argv[i + 1]
            index_path = os.path.join(output_dir, 'index', 'index.json')
            if not os.path.exists(index_path):
                index_path = None
            i += 2
        elif sys.argv[i] == '--index' and i + 1 < len(sys.argv):
            index_path = sys.argv[i + 1]
            i += 2
        else:
            print(f'Unknown or incomplete argument: {sys.argv[i]}', file=sys.stderr)
            sys.exit(1)

    count = batch_extract(docx_path, output_dir, index_path)
    print(f'Extracted {count} sections to {output_dir}/sections/', file=sys.stderr)


if __name__ == '__main__':
    main()
