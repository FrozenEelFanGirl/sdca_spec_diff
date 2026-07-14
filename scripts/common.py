"""
Shared OOXML utilities for the SDCA SpecDiff project.

Constants, parsing helpers, and rendering logic used across extract, search,
and comparison scripts.  Import from here instead of duplicating.
"""

import os
import re
from lxml import etree

# ── XML namespaces ──────────────────────────────────────────────────────────

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PIC = 'http://schemas.openxmlformats.org/drawingml/2006/picture'
VML = 'urn:schemas-microsoft-com:vml'
NS = {'w': W}

# ── Style sets ──────────────────────────────────────────────────────────────

TOC_STYLES = {'TOC1', 'TOC2', 'TOC3', 'TOC4', 'TOC5', 'TableofFigures'}

BULLET_STYLES = {
    'List1', 'List2', 'List3', 'List4', 'List5',
    'ListBullet', 'ListBullet2', 'ListBullet3', 'ListBullet4', 'ListBullet5',
    'ListContinue', 'ListContinue2', 'ListContinue3', 'ListContinue4', 'ListContinue5',
    'RequirementList1', 'RequirementList2',
    'RecommendationList1', 'RecommendationList2',
    'PermissionList1', 'PermissionList2',
}

NUMBERED_STYLES = {
    'ListNumber', 'ListNumber1', 'ListNumber2', 'ListNumber3', 'ListNumber4', 'ListNumber5',
    'ListNumber1manual', 'ListNumber2manual', 'ListNumber3manual',
}

CODE_STYLES = {'Code', 'CodeExample', 'CodeSmall'}

NOTE_HEAD_STYLES = {'NoteHead'}
NOTE_BODY_STYLES = {'NoteBody'}

DEFINITION_STYLES = {'Definition'}
FIGURE_TITLE_STYLES = {'FigureTitle'}
TABLE_TITLE_STYLES = {'TableTitle'}


# ── TOC parsing ─────────────────────────────────────────────────────────────

def parse_toc(doc_xml_bytes):
    """Parse TOC field entries to build section_number -> heading_text maps.

    Returns (num_to_heading, heading_to_num).
    """
    root = etree.fromstring(doc_xml_bytes)
    body = root.find(f'{{{W}}}body')
    if body is None:
        return {}, {}

    toc_entries = []
    for child in body:
        if child.tag != f'{{{W}}}p':
            continue
        instr_texts = child.findall(f'.//{{{W}}}instrText', NS)
        if not instr_texts:
            continue
        instr = ' '.join([(it.text or '') for it in instr_texts])
        if 'PAGEREF' not in instr:
            continue

        full_text = ''.join(t.text or '' for t in child.iter(f'{{{W}}}t')).strip()
        m = re.match(r'^([\d]+(?:\.[\d]+)*)(.+?)(\d+)$', full_text)
        if m:
            num = m.group(1)
            heading = m.group(2).strip()
            toc_entries.append((num, heading))

    num_to_heading = {}
    heading_to_num = {}
    for num, heading in toc_entries:
        num_to_heading[num] = heading
        heading_to_num[heading.lower()] = num

    return num_to_heading, heading_to_num


# ── Style resolution ────────────────────────────────────────────────────────

def build_style_map(styles_xml):
    """Parse styles.xml and resolve outline levels through inheritance."""
    root = etree.fromstring(styles_xml)
    style_info = {}
    for style in root.iter(f'{{{W}}}style'):
        sid = style.get(f'{{{W}}}styleId')
        based_on = None
        bo = style.find('w:basedOn', NS)
        if bo is not None:
            based_on = bo.get(f'{{{W}}}val')
        outline_lvl = None
        pPr = style.find('w:pPr', NS)
        if pPr is not None:
            ol = pPr.find('w:outlineLvl', NS)
            if ol is not None:
                outline_lvl = int(ol.get(f'{{{W}}}val'))
        style_info[sid] = {'outline': outline_lvl, 'basedOn': based_on}

    def resolve_outline(sid, visited=None):
        if visited is None:
            visited = set()
        if sid not in style_info or sid in visited:
            return None
        visited.add(sid)
        info = style_info[sid]
        if info['outline'] is not None:
            return info['outline']
        if info['basedOn']:
            return resolve_outline(info['basedOn'], visited)
        return None

    for sid in style_info:
        style_info[sid]['resolved_outline'] = resolve_outline(sid)
    return style_info


# ── Markdown conversion ─────────────────────────────────────────────────────

def para_to_markdown(p_elem):
    """Convert a w:p element to Markdown text with bold/italic formatting."""
    parts = []
    for run in p_elem.iter(f'{{{W}}}r'):
        rPr = run.find(f'{{{W}}}rPr', NS)
        is_bold = False
        is_italic = False
        if rPr is not None:
            b = rPr.find(f'{{{W}}}b', NS)
            if b is not None:
                val = b.get(f'{{{W}}}val')
                is_bold = val != '0' and val != 'false'
            i = rPr.find(f'{{{W}}}i', NS)
            if i is not None:
                val = i.get(f'{{{W}}}val')
                is_italic = val != '0' and val != 'false'

        t = run.find(f'{{{W}}}t')
        if t is None or not t.text:
            continue
        text = t.text

        if is_bold and is_italic:
            text = f'***{text}***'
        elif is_bold:
            text = f'**{text}**'
        elif is_italic:
            text = f'*{text}*'

        parts.append(text)

    return ''.join(parts)


def table_to_markdown(tbl_elem):
    """Convert a w:tbl element to a Markdown table."""
    rows = tbl_elem.findall(f'{{{W}}}tr')
    if not rows:
        return ''

    lines = []
    for ri, row in enumerate(rows):
        cells = row.findall(f'{{{W}}}tc')
        cell_texts = []
        for cell in cells:
            paras = []
            for p in cell.findall(f'{{{W}}}p'):
                text = para_to_markdown(p).strip()
                if text:
                    paras.append(text.replace('|', '\\|').replace('\n', ' '))
            cell_texts.append(' '.join(paras))
        lines.append('| ' + ' | '.join(cell_texts) + ' |')
        if ri == 0:
            lines.append('|' + '|'.join(['---' for _ in cells]) + '|')

    return '\n'.join(lines)


# ── Relationships ───────────────────────────────────────────────────────────

def parse_rels(zip_file):
    """Parse document.xml.rels to map rId -> target path."""
    rels_xml = zip_file.read('word/_rels/document.xml.rels')
    root = etree.fromstring(rels_xml)
    rels = {}
    for rel in root:
        rid = rel.get('Id')
        target = rel.get('Target')
        if rid and target:
            rels[rid] = target
    return rels


# ── List indentation ────────────────────────────────────────────────────────

def get_list_indent(style_id):
    """Extract indent level from list style name. Returns 0-based indent."""
    if style_id is None:
        return 0
    m = re.search(r'(\d)$', style_id)
    if m:
        return int(m.group(1)) - 1
    return 0


# ── File naming ─────────────────────────────────────────────────────────────

def section_file(num, heading):
    """Generate section file name from section number and heading."""
    slug = re.sub(r'[^\w\s-]', '', heading).strip().replace(' ', '_')
    return f'{num}_{slug}.md'


# ── Cross-reference resolution ──────────────────────────────────────────────

def resolve_refs(text, index):
    """Resolve cross-references (Section X.Y, Table N, Figure N) using the index."""
    lines = text.split('\n')
    result = []

    for line in lines:
        stripped = line.strip()
        if (stripped.startswith('*Figure') or stripped.startswith('*Table') or
            stripped.startswith('**Table') or
            stripped.startswith('![Figure') or stripped.startswith('![Table') or
            stripped.startswith('#')):
            result.append(line)
            continue

        def replace_section(m):
            num = m.group(1)
            entry = index.get('sections', {}).get(num)
            if entry:
                return f'[Section {num} — {entry["heading"]}]({entry["file"]})'
            return m.group(0)

        line = re.sub(r'Section\s+(\d+(?:\.\d+)+)', replace_section, line)

        def replace_table(m):
            num = m.group(1)
            entry = index.get('tables', {}).get(num)
            if entry:
                return f'[Table {num} — {entry["caption"]}]({entry["file"]})'
            return m.group(0)

        line = re.sub(r'Table\s+(\d+)', replace_table, line)

        def replace_figure(m):
            num = m.group(1)
            entry = index.get('figures', {}).get(num)
            if entry:
                return f'[Figure {num} — {entry["caption"]}]({entry["file"]})'
            return m.group(0)

        line = re.sub(r'Figure\s+(\d+)', replace_figure, line)

        result.append(line)

    return '\n'.join(result)


# ── Sorting ─────────────────────────────────────────────────────────────────

def sort_key(num_str):
    """Sort key for section numbers like '5.11.3'."""
    try:
        return tuple(int(n) for n in num_str.split('.'))
    except (ValueError, AttributeError):
        return (9999,)


# ── Markdown rendering ──────────────────────────────────────────────────────

def render_output_to_markdown(output):
    """Convert a list of (type, data) tuples into a Markdown string.

    Types and their data shapes:
      ('heading',           (level, text))
      ('bullet',            (indent, text))
      ('numbered',          (indent, counter, text))
      ('code',              text)
      ('note_head',         text)
      ('note_body',         text)
      ('definition',        text)
      ('image_with_caption',(filename, caption))
      ('image_only',        filename)
      ('figure_title',      text)
      ('table_with_caption',(md_table, caption, table_num))
      ('table_title',       text)
      ('table',             md_table)
      ('body',              text)
    """
    lines = []
    prev_type = None

    for item in output:
        typ = item[0]

        if typ == 'heading':
            lvl, content = item[1]
            if lines:
                lines.append('')
            lines.append(f'{"#" * (lvl + 1)} {content}')
            lines.append('')

        elif typ in ('bullet', 'numbered'):
            # Blank line before a list when following body text,
            # so renderers don't merge the paragraph into the list.
            if prev_type in ('body', 'note_body', 'definition'):
                if lines and lines[-1] != '':
                    lines.append('')
            if typ == 'bullet':
                indent, content = item[1]
                prefix = '    ' * indent + '- '
            else:
                indent, num, content = item[1]
                prefix = '    ' * indent + f'{num}. '
            lines.append(prefix + content)

        elif typ == 'code':
            content = item[1]
            if prev_type != 'code':
                if lines and lines[-1] != '':
                    lines.append('')
                lines.append('```')
            lines.append(content)

        elif typ == 'note_head':
            content = item[1]
            if lines and lines[-1] != '':
                lines.append('')
            lines.append(f'**{content}**')

        elif typ == 'note_body':
            lines.append(f'> {item[1]}')

        elif typ == 'definition':
            lines.append(f'*{item[1]}*')

        elif typ == 'image_with_caption':
            filename, caption = item[1]
            if lines and lines[-1] != '':
                lines.append('')
            lines.append(f'![{caption}](../images/{filename})')
            lines.append('')
            lines.append(f'*{caption}*')

        elif typ == 'image_only':
            filename = item[1]
            if lines and lines[-1] != '':
                lines.append('')
            lines.append(f'![Figure](../images/{filename})')
            lines.append('')

        elif typ == 'figure_title':
            if lines and lines[-1] != '':
                lines.append('')
            lines.append(f'*{item[1]}*')

        elif typ == 'table_with_caption':
            md_table, caption, table_num = item[1]
            if lines and lines[-1] != '':
                lines.append('')
            lines.append(f'**{caption}**')
            lines.append('')
            lines.append(md_table)
            lines.append('')

        elif typ == 'table_title':
            if lines and lines[-1] != '':
                lines.append('')
            lines.append(f'**{item[1]}**')

        elif typ == 'table':
            if lines and lines[-1] != '':
                lines.append('')
            lines.append(item[1])
            lines.append('')

        else:  # body
            # Blank line after a list before body text resumes.
            if prev_type in ('bullet', 'numbered'):
                if lines and lines[-1] != '':
                    lines.append('')
            lines.append(item[1])

        prev_type = typ

    # Close any open code block
    if output and output[-1][0] == 'code':
        lines.append('```')
        lines.append('')

    # Collapse runs of blank lines
    result = []
    blank_count = 0
    for line in lines:
        if line == '':
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)

    return '\n'.join(result).strip() + '\n'
