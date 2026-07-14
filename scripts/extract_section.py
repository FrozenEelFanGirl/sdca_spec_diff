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
    W, A, R, NS, VML,
    TOC_STYLES, BULLET_STYLES, NUMBERED_STYLES, CODE_STYLES,
    NOTE_HEAD_STYLES, NOTE_BODY_STYLES, DEFINITION_STYLES,
    FIGURE_TITLE_STYLES, TABLE_TITLE_STYLES,
    build_style_map, parse_toc, parse_rels,
    para_to_markdown, get_list_indent, table_to_markdown,
    section_file, resolve_refs, render_output_to_markdown,
)


def _extract_image_file(rid, rels_map, zip_file, images_dir):
    """Extract an image from the docx and convert to PNG. Returns saved filename."""
    target = rels_map[rid]
    zip_path = 'word/' + target
    img_data = zip_file.read(zip_path)

    name, ext = os.path.splitext(os.path.basename(target))
    png_name = name + '.png'
    png_path = os.path.join(images_dir, png_name)

    if ext.lower() in ('.emf', '.wmf'):
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(img_data))
            img.save(png_path, 'PNG')
        except Exception:
            with open(os.path.join(images_dir, os.path.basename(target)), 'wb') as f:
                f.write(img_data)
            return os.path.basename(target)
    else:
        with open(png_path, 'wb') as f:
            f.write(img_data)

    return png_name


def _find_image_in_paragraph(p_elem, zip_file, rels_map, images_dir):
    """Check a paragraph for embedded images/OLE objects and extract them.
    Returns saved filename or None."""
    # Regular drawing (w:r > w:drawing > a:blip)
    for drawing in p_elem.findall(f'.//{{{W}}}drawing'):
        for blip in drawing.findall(f'.//{{{A}}}blip'):
            embed = blip.get(f'{{{R}}}embed')
            if embed and embed in rels_map:
                return _extract_image_file(embed, rels_map, zip_file, images_dir)

    # OLE object preview (w:r > w:object > v:imagedata)
    for obj in p_elem.findall(f'.//{{{W}}}object'):
        for imagedata in obj.findall(f'.//{{{VML}}}imagedata'):
            rid = imagedata.get(f'{{{R}}}id')
            if rid and rid in rels_map:
                return _extract_image_file(rid, rels_map, zip_file, images_dir)

    return None


def _peek_next_figure_title(p_elem):
    """Look ahead from an image paragraph to find a FigureTitle caption.
    Returns (caption_text, caption_element) or (None, None)."""
    next_sib = p_elem.getnext()
    while next_sib is not None and next_sib.tag == f'{{{W}}}p':
        pPr = next_sib.find(f'{{{W}}}pPr', NS)
        style_id = None
        if pPr is not None:
            pStyle = pPr.find(f'{{{W}}}pStyle', NS)
            if pStyle is not None:
                style_id = pStyle.get(f'{{{W}}}val')

        text = para_to_markdown(next_sib).strip()
        if text:
            if style_id in FIGURE_TITLE_STYLES:
                return text, next_sib
            else:
                return None, None
        next_sib = next_sib.getnext()
    return None, None


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
    root = etree.fromstring(doc_xml)
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
            if found_target:
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


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    if len(sys.argv) < 3 and sys.argv[1] != '--from-config':
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
        section_id = sys.argv[3] if len(sys.argv) >= 4 else None
        if section_id is None:
            print('Error: --from-config requires <section_id>', file=sys.stderr)
            sys.exit(1)
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
