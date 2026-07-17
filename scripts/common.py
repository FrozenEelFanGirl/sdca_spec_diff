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
Shared OOXML utilities for the SDCA SpecDiff project.

Constants, parsing helpers, and rendering logic used across extract, search,
and comparison scripts.  Import from here instead of duplicating.
"""

import os
import re
import sys
import logging
from lxml import etree

# ── XML namespaces ──────────────────────────────────────────────────────────

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

# Secure parser: entity expansion is disabled to prevent billion-laughs
# and similar XML entity-expansion DoS attacks in untrusted docx input.
_SECURE_PARSER = etree.XMLParser(resolve_entities=False)


def parse_xml(xml_bytes):
    """Parse XML bytes with entity expansion disabled."""
    return etree.fromstring(xml_bytes, _SECURE_PARSER)
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

# ── Logging ──────────────────────────────────────────────────────────────────

def get_logger(name):
    """Return a logger writing to stderr with consistent formatting.
    Repeated calls with the same *name* return the same logger instance."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter('%(levelname).4s [%(name)s] %(message)s'))
        logger.addHandler(h)
        logger.setLevel(logging.WARNING)
    return logger


# ── Spelling variants ────────────────────────────────────────────────────────

SPELLING_VARIANTS = {
    # British → American (and other common variants)
    'grey': 'gray',
    'colour': 'color',
    'centre': 'center',
    'behaviour': 'behavior',
    'analyse': 'analyze',
    'metre': 'meter',
    'organise': 'organize',
    'realise': 'realize',
    'defence': 'defense',
    'licence': 'license',
    'analogue': 'analog',
    'catalogue': 'catalog',
    'modelled': 'modeled',
    'travelling': 'traveling',
    'labelled': 'labeled',
    'fuelled': 'fueled',
    'signalling': 'signaling',
    'programme': 'program',
    'artefact': 'artifact',
    'fibre': 'fiber',
    'litre': 'liter',
    'lustre': 'luster',
    'manoeuvre': 'maneuver',
    'mould': 'mold',
    'practise': 'practice',
    'sceptic': 'skeptic',
    'storey': 'story',
    'sulphur': 'sulfur',
    'tyre': 'tire',
}


# ── TOC parsing ─────────────────────────────────────────────────────────────

def parse_toc(doc_xml_bytes):
    """Parse TOC field entries to build section_number -> heading_text maps.

    Returns (num_to_heading, heading_to_num).
    """
    root = parse_xml(doc_xml_bytes)
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

        # TOC entry structure: <num> <tab> <heading> <tab> <PAGEREF page>.
        # Split on tab runs and stop at the PAGEREF field so headings that
        # end in digits (e.g. "... IT11") are not confused with the page
        # number.
        segments = ['']
        for el in child.iter():
            if el.tag == f'{{{W}}}fldChar':
                break
            if el.tag == f'{{{W}}}tab':
                segments.append('')
            elif el.tag == f'{{{W}}}t' and el.text:
                segments[-1] += el.text

        num, heading = None, None
        parts = [s.strip() for s in segments if s.strip()]
        if len(parts) >= 2:
            if re.match(r'^[\d]+(?:\.[\d]+)*$', parts[0]):
                num, heading = parts[0], parts[1]
        if num is None:
            # Fallback for entries without the tab structure. The trailing
            # (\d+) is the page number; headings ending in digits may lose
            # them here.
            full_text = ''.join(t.text or '' for t in child.iter(f'{{{W}}}t')).strip()
            m = re.match(r'^([\d]+(?:\.[\d]+)*)(.+?)(\d+)$', full_text)
            if m:
                num, heading = m.group(1), m.group(2).strip()
        if num:
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
    root = parse_xml(styles_xml)
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
        text = t.text.replace('<', r'\<').replace('>', r'\>')

        if is_bold and is_italic:
            text = f'***{text}***'
        elif is_bold:
            text = f'**{text}**'
        elif is_italic:
            text = f'*{text}*'

        parts.append(text)

    return ''.join(parts)


def table_to_markdown(tbl_elem):
    """Convert a w:tbl element to a Markdown table.
    Warns via logging when the table element has no data rows."""
    rows = tbl_elem.findall(f'{{{W}}}tr')
    if not rows:
        get_logger('common').warning('Empty table element found (zero w:tr rows)')
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
    root = parse_xml(rels_xml)
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
    """Generate section file name from section number and heading.

    Punctuation is stripped first, then all whitespace (including NBSP and
    en-spaces) is collapsed to single underscores, so index and extraction
    derive identical names from slightly different heading sources.
    """
    slug = re.sub(r'[^\w\s-]', '', heading)
    slug = re.sub(r'\s+', ' ', slug).strip().replace(' ', '_')
    return f'{num}_{slug}.md'


# ── Deep-heading (####/#####) anchoring ─────────────────────────────────────
# Deep headings are mapping nodes below section numbering.  ###### lines, if
# they ever appear, are original paragraph text (notes) — never anchors and
# never scope boundaries.

DEEP_ANCHOR_RE = re.compile(r'^(#{4,5})\s+(.*)$')


def unescape_heading(h):
    """Undo markdown escapes so heading text compares across index and files."""
    return h.replace(r'\<', '<').replace(r'\>', '>').replace(r'\*', '*')


def direct_children(num, sections):
    """Section numbers one level below *num*, in document order."""
    depth = len(num.split('.')) + 1
    prefix = num + '.'
    return [k for k in sections
            if k.startswith(prefix) and len(k.split('.')) == depth]


def own_scope(text, sections, num):
    """A section's own content: its subtree text cut at the first
    child-section heading."""
    kids = direct_children(num, sections)
    if not kids:
        return text
    info = sections[kids[0]]
    hashes = '#' * (info['level'] + 1)
    target = unescape_heading(info['heading'].strip())
    lines = text.split('\n')
    for i, line in enumerate(lines):
        m = re.match(r'^(#+)\s+(.*)$', line)
        if m and m.group(1) == hashes and unescape_heading(m.group(2).strip()) == target:
            return '\n'.join(lines[:i])
    for i, line in enumerate(lines):
        m = re.match(r'^(#+)\s', line)
        if m and m.group(1) == hashes:
            get_logger('common').warning(
                'own_scope: child heading %r not found verbatim in §%s; '
                'cutting at first level-%d heading', target, num, len(hashes))
            return '\n'.join(lines[:i])
    get_logger('common').warning(
        'own_scope: no level-%d heading found in §%s; using whole text',
        len(hashes), num)
    return text


def collect_deep_headings(sections_dir, sections):
    """Inventory of ####/##### headings within each section's own scope.

    Returns a list of records in document order:
      {id, parent, container, path, heading, hashes, occurrence, order}
    *id* is '<parent>#<path joined with #>', with ' [n]' appended on exact
    path collisions; *occurrence* is that collision ordinal (for slicing);
    *container* is the immediate enclosing node id (a pseudo id, or the
    parent section number for top-level deep headings).
    """
    out = []
    order = 0
    for num, e in sections.items():
        fname = e['file'].rsplit('/', 1)[-1]
        fpath = os.path.join(str(sections_dir), fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, encoding='utf-8') as f:
            text = f.read()
        text = own_scope(text, sections, num)
        stack = []
        seen = {}
        for line in text.split('\n'):
            m = DEEP_ANCHOR_RE.match(line)
            if not m:
                continue
            h = len(m.group(1))
            t = unescape_heading(m.group(2).strip())
            while stack and stack[-1][0] >= h:
                stack.pop()
            path = [s[1] for s in stack] + [t]
            base_id = num + '#' + '#'.join(path)
            n = seen.get(base_id, 0) + 1
            seen[base_id] = n
            node_id = base_id if n == 1 else f'{base_id} [{n}]'
            container = stack[-1][2] if stack else num
            out.append({'id': node_id, 'parent': num, 'container': container,
                        'path': path, 'heading': t, 'hashes': h,
                        'occurrence': n, 'order': order})
            stack.append((h, t, node_id))
            order += 1
    return out


def slice_heading_scope(text, path, hashes, occurrence=1):
    """Slice a deep node's scope out of its parent section's own-scope text:
    from the heading whose path matches, to the next heading with hash count
    <= its own.  Returns None if not found."""
    lines = text.split('\n')
    stack = []
    count = 0
    start = None
    for i, line in enumerate(lines):
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if not m:
            continue
        h = len(m.group(1))
        if start is not None:
            if h <= hashes:
                return '\n'.join(lines[start:i])
            continue
        if h < 4 or h > 5:
            continue
        t = unescape_heading(m.group(2).strip())
        while stack and stack[-1][0] >= h:
            stack.pop()
        cur = [s[1] for s in stack] + [t]
        stack.append((h, t))
        if h == hashes and cur == list(path):
            count += 1
            if count == occurrence:
                start = i
    if start is not None:
        return '\n'.join(lines[start:])
    return None


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


# ── Image extraction helpers ─────────────────────────────────────────────────

def extract_image_file(rid, rels_map, zip_file, images_dir):
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


def find_image_in_paragraph(p_elem, zip_file, rels_map, images_dir):
    """Check a paragraph for embedded images/OLE objects and extract them.
    Returns saved filename or None."""
    # Regular drawing (w:r > w:drawing > a:blip)
    for drawing in p_elem.findall(f'.//{{{W}}}drawing'):
        for blip in drawing.findall(f'.//{{{A}}}blip'):
            embed = blip.get(f'{{{R}}}embed')
            if embed and embed in rels_map:
                return extract_image_file(embed, rels_map, zip_file, images_dir)

    # OLE object preview (w:r > w:object > v:imagedata)
    for obj in p_elem.findall(f'.//{{{W}}}object'):
        for imagedata in obj.findall(f'.//{{{VML}}}imagedata'):
            rid = imagedata.get(f'{{{R}}}id')
            if rid and rid in rels_map:
                return extract_image_file(rid, rels_map, zip_file, images_dir)

    return None


def peek_next_figure_title(p_elem):
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


# ── Shared section content processing ────────────────────────────────────────

def process_content_paragraph(child, z, rels_map, images_dir, handled_elements,
                              style_id, text, num_counters, pending_caption):
    """Process a body paragraph within a section.

    Handles image extraction, style dispatch (bullet/numbered/code/note/
    definition/figure-title/table-title/body), and pending caption tracking.

    Mutates *num_counters* and *handled_elements* in place.
    Returns (output_item, new_pending_caption).
    *output_item* is None when the paragraph should be skipped.
    """
    # ── Image extraction ──
    if rels_map:
        img_filename = find_image_in_paragraph(child, z, rels_map, images_dir)
        if img_filename:
            caption, caption_elem = peek_next_figure_title(child)
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
                return ('image_with_caption', (img_filename, caption)), pending_caption
            else:
                return ('image_only', img_filename), pending_caption

    if not text:
        return None, pending_caption

    if child in handled_elements:
        return None, pending_caption

    # ── Style dispatch ──
    if style_id in BULLET_STYLES:
        indent = get_list_indent(style_id)
        for k in list(num_counters):
            if k > indent:
                del num_counters[k]
        return ('bullet', (indent, text)), pending_caption

    if style_id in NUMBERED_STYLES:
        indent = get_list_indent(style_id)
        for k in list(num_counters):
            if k > indent:
                del num_counters[k]
        num_counters[indent] = num_counters.get(indent, 0) + 1
        return ('numbered', (indent, num_counters[indent], text)), pending_caption

    if style_id in CODE_STYLES:
        return ('code', text), pending_caption

    if style_id in NOTE_HEAD_STYLES:
        return ('note_head', text), pending_caption

    if style_id in NOTE_BODY_STYLES:
        return ('note_body', text), pending_caption

    if style_id in DEFINITION_STYLES:
        return ('definition', text), pending_caption

    if style_id in FIGURE_TITLE_STYLES:
        return ('figure_title', text), pending_caption

    if style_id in TABLE_TITLE_STYLES:
        m = re.match(r'Table\s+(\d+)\s+(.+)', text)
        if m:
            return None, (text, m.group(1))
        else:
            return ('table_title', text), pending_caption

    # Body text — reset counters on transition from structured content
    num_counters.clear()
    return ('body', text), pending_caption


def process_content_table(tbl_elem, pending_caption, tables_written):
    """Process a w:tbl element within a section.

    Mutates *tables_written* in place.
    Returns (output_item, new_pending_caption).
    """
    md_table = table_to_markdown(tbl_elem)
    if md_table and pending_caption:
        caption_text, table_num = pending_caption
        table_md = f'**{caption_text}**\n\n{md_table}\n'
        tables_written[table_num] = table_md
        return ('table_with_caption', (md_table, caption_text, table_num)), None
    elif md_table:
        return ('table', md_table), pending_caption
    return None, pending_caption


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

    # Collapse runs of blank lines, except inside fenced code blocks
    # where blank lines are meaningful content.
    result = []
    blank_count = 0
    in_fence = False
    for line in lines:
        if line.startswith('```'):
            in_fence = not in_fence
            blank_count = 0
            result.append(line)
        elif in_fence:
            blank_count = 0
            result.append(line)
        elif line == '':
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)

    return '\n'.join(result).strip() + '\n'
