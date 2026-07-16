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
Extract a section from an SDCA specification .docx file as clean Markdown.

Usage:
  python extract_section.py <docx_path> <section_id> [--output-dir DIR] [--index PATH]

<section_id> can be:
  - A section number from the TOC: "4", "4.4.6", "5.1"
  - A heading text keyword: "Smart Amp", "UAJ", "HID Report"

Output: writes section to doc/output/sections/, tables to doc/output/tables/,
  images to doc/output/images/.  Cross-references are resolved via index.json.

Examples:
  python -X utf8 scripts/extract_section.py --from-config base "5.1.2"
  python -X utf8 scripts/extract_section.py <docx_path> "5.1.2" --output-dir <dir>
"""

import sys
import os
import re
import json
import zipfile
from lxml import etree

from common import (
    W, NS,
    TOC_STYLES,
    build_style_map, parse_toc, parse_rels,
    para_to_markdown, section_file, resolve_refs, render_output_to_markdown,
    sort_key, parse_xml,
    process_content_paragraph, process_content_table,
)


def extract_section(docx_path, section_id, output_dir='doc/output', index_path=None):
    """Extract a section and all its subsections as Markdown.
    Writes: section file to sections/, tables to tables/, images to images/.
    Returns (section_text, section_num, section_heading)."""
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
    root = parse_xml(doc_xml)
    body = root.find(f'{{{W}}}body')

    rels_map = parse_rels(z)

    num_to_heading, heading_to_num = parse_toc(doc_xml)

    # Resolve section_id to target heading text
    target_heading = None
    exact_heading_match = False
    if section_id in num_to_heading:
        target_heading = num_to_heading[section_id]
        exact_heading_match = True
    else:
        section_lower = section_id.lower()
        for toc_heading_lower, num in heading_to_num.items():
            if section_lower in toc_heading_lower:
                target_heading = num_to_heading[num]
                break

    if target_heading is None:
        print(f'Error: could not find section "{section_id}" in document TOC', file=sys.stderr)
        if num_to_heading:
            print('Available section numbers:', file=sys.stderr)
            for num in sorted(num_to_heading.keys(), key=lambda n: tuple(int(x) for x in n.split('.')))[:40]:
                print(f'  {num}: {num_to_heading[num]}', file=sys.stderr)
        sys.exit(1)

    def normalize_h(text):
        text = re.sub(r'^[\dA-Z\.]+\s*', '', text).strip()
        return text.lower().replace('–', '-').replace('—', '-')

    target_normalized = normalize_h(target_heading)

    found_target = False
    target_level = None
    target_section_num = section_id if section_id in num_to_heading else None
    heading_stack = []
    output = []
    num_counters = {}
    handled_elements = set()
    pending_caption = None
    tables_written = {}

    for child in body:
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
                while heading_stack and heading_stack[-1][1] >= lvl:
                    heading_stack.pop()
                heading_stack.append((text, lvl))

                if not found_target:
                    h_norm = normalize_h(text)
                    if exact_heading_match:
                        if h_norm == target_normalized:
                            found_target = True
                    else:
                        if h_norm == target_normalized or target_normalized in h_norm:
                            found_target = True
                    if found_target:
                        target_level = lvl
                        heading_stack = [(text, lvl)]
                        output.append(('heading', (lvl, text)))
                else:
                    if lvl <= target_level:
                        break
                    output.append(('heading', (lvl, text)))

            elif found_target:
                item, pending_caption = process_content_paragraph(
                    child, z, rels_map, images_dir, handled_elements,
                    style_id, text, num_counters, pending_caption)
                if item is not None:
                    output.append(item)

        elif child.tag == f'{{{W}}}tbl':
            if found_target:
                item, pending_caption = process_content_table(
                    child, pending_caption, tables_written)
                if item is not None:
                    output.append(item)

    if pending_caption:
        output.append(('table_title', pending_caption[0]))
        pending_caption = None

    if not found_target:
        print(f'Error: heading for "{target_heading}" not found in document body', file=sys.stderr)
        sys.exit(1)

    text = render_output_to_markdown(output)

    # Resolve cross-references
    if index_path:
        with open(index_path, 'r', encoding='utf-8') as f:
            idx = json.load(f)
        text = resolve_refs(text, idx)

    # Write standalone table files
    for table_num, table_md in tables_written.items():
        table_path = os.path.join(tables_dir, f'Table{table_num}.md')
        with open(table_path, 'w', encoding='utf-8') as f:
            f.write(table_md)

    # Determine section number from TOC for the target heading
    section_num = None
    if target_heading:
        for num, heading in num_to_heading.items():
            if heading == target_heading:
                section_num = num
                break

    return text, section_num, target_heading


def extract_sections(docx_path, output_dir, index_path=None):
    """Extract all sections from a docx in a single pass.

    Opens the docx once, maps body children to sections via heading positions,
    and writes each section to its own markdown file.
    Returns the number of sections extracted.
    """
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
    root = parse_xml(doc_xml)
    body = root.find(f'{{{W}}}body')

    rels_map = parse_rels(z)
    num_to_heading, heading_to_num = parse_toc(doc_xml)

    index_data = None
    if index_path and os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)

    def _normalize_heading(h):
        """Normalize heading text for robust comparison."""
        h = h.replace(r'\<', '<').replace(r'\>', '>').replace(r'\*', '*')
        h = re.sub(r'#\s+(\d)', r'#\1', h)
        h = re.sub(r'\s+', ' ', h)
        h = h.replace('–', '-').replace('—', '-').lower()
        h = re.sub(r'^[\dA-Z\.]+\s*', '', h).strip()
        return h

    # Pre-normalize TOC headings
    toc_norm = {num: _normalize_heading(h) for num, h in num_to_heading.items()}

    # Find all heading elements and their positions in the body
    heading_positions = []  # (child_index, section_num, heading_text, level)
    body_children = list(body)
    toc_matched: set[str] = set()  # track TOC entries already consumed
    unmatched_body = []  # (idx, text, lvl, h_norm) — body headings not yet matched

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
        h_norm = _normalize_heading(text)
        section_num = None
        for num, tn in toc_norm.items():
            if num in toc_matched:
                continue
            if tn == h_norm:
                section_num = num
                toc_matched.add(num)
                break
        if section_num:
            heading_positions.append((idx, section_num, text, lvl))
        else:
            unmatched_body.append((idx, text, lvl, h_norm))

    # Second pass: for unmatched TOC entries, try prefix match
    # or section-number-in-heading-text against unmatched body headings.
    unmatched_toc = [(num, tn) for num, tn in toc_norm.items()
                     if num not in toc_matched]
    for num, tn in unmatched_toc:
        best = None
        for bi, (idx, text, lvl, h_norm) in enumerate(unmatched_body):
            # Prefix match: TOC heading is a prefix of body heading
            # (handles parse_toc regex truncating trailing digits, e.g.
            #  "Microphone Geometry Reported in IT" vs "... IT11")
            if h_norm.startswith(tn) and len(tn) >= len(h_norm) * 0.6:
                best = (bi, idx, num, text, lvl)
                break
            # Section number extracted from heading text matches TOC
            m = re.match(r'^([\d]+(?:\.[\d]+)*)\s', text)
            if m and m.group(1) == num:
                best = (bi, idx, num, text, lvl)
                break
        if best is not None:
            bi, idx, num, text, lvl = best
            heading_positions.append((idx, num, text, lvl))
            toc_matched.add(num)
            del unmatched_body[bi]

    # Third pass: remaining body headings with section numbers not in TOC
    for idx, text, lvl, h_norm in unmatched_body:
        m = re.match(r'^([\d]+(?:\.[\d]+)*)\s', text)
        if m:
            heading_positions.append((idx, m.group(1), text, lvl))

    section_to_pos = {}
    for pos_idx, (child_idx, section_num, heading_text, lvl) in enumerate(heading_positions):
        section_to_pos[section_num] = pos_idx

    extracted_count = 0
    all_section_nums = sorted(
        set(list(num_to_heading.keys()) + [sn for _, sn, _, _ in heading_positions]),
        key=sort_key)

    for section_num in all_section_nums:
        if section_num not in section_to_pos:
            continue

        pos_idx = section_to_pos[section_num]
        child_idx, heading_text, target_level = (
            heading_positions[pos_idx][0],
            heading_positions[pos_idx][2],
            heading_positions[pos_idx][3],
        )

        end_idx = len(body_children)
        for j in range(pos_idx + 1, len(heading_positions)):
            if heading_positions[j][3] <= target_level:
                end_idx = heading_positions[j][0]
                break

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

                item, pending_caption = process_content_paragraph(
                    child, z, rels_map, images_dir, handled_elements,
                    style_id, text, num_counters, pending_caption)
                if item is not None:
                    output.append(item)

            elif child.tag == f'{{{W}}}tbl':
                item, pending_caption = process_content_table(
                    child, pending_caption, tables_written)
                if item is not None:
                    output.append(item)

        if pending_caption:
            output.append(('table_title', pending_caption[0]))

        text = render_output_to_markdown(output)

        if index_data:
            text = resolve_refs(text, index_data)

        filename = section_file(section_num, heading_text)
        filepath = os.path.join(sections_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(text)

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

    if sys.argv[1] == '--from-config':
        from config import load_config
        cfg = load_config()
        target = sys.argv[2] if len(sys.argv) >= 3 else 'base'
        ver = cfg.base if target == 'base' else cfg.comparison
        docx_path = str(ver.docx)
        output_dir = str(ver.output_dir)
        index_path = str(ver.index_file) if ver.index_file.exists() else None

        if len(sys.argv) >= 4 and sys.argv[3] == '--all':
            count = extract_sections(docx_path, output_dir, index_path)
            print(f'Extracted {count} sections to {output_dir}/sections/', file=sys.stderr)
            return

        section_id = sys.argv[3] if len(sys.argv) >= 4 else None
        if section_id is None:
            print('Error: --from-config requires <section_id> or --all', file=sys.stderr)
            sys.exit(1)

        text, section_num, section_heading = extract_section(
            docx_path, section_id, output_dir=output_dir, index_path=index_path)
    else:
        docx_path = sys.argv[1]
        section_id = sys.argv[2]
        output_dir = 'doc/output'
        index_path = os.path.join(output_dir, 'index', 'index.json')
        if not os.path.exists(index_path):
            index_path = None

        i = 3
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

        text, section_num, section_heading = extract_section(
            docx_path, section_id, output_dir=output_dir, index_path=index_path)

    if section_num:
        slug = re.sub(r'[^\w\s-]', '', section_heading).strip().replace(' ', '_')
        section_file_path = os.path.join(output_dir, 'sections', f'{section_num}_{slug}.md')
        with open(section_file_path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'Section: {section_file_path}', file=sys.stderr)
    else:
        slug = re.sub(r'[^\w\s-]', '', section_id).strip().replace(' ', '_')
        section_file_path = os.path.join(output_dir, 'sections', f'{slug}.md')
        with open(section_file_path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'Section: {section_file_path}', file=sys.stderr)


if __name__ == '__main__':
    main()
