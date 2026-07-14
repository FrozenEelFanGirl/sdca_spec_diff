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
Search base docx body text for sections matching a keyword phrase.

Output: Markdown table with match counts.
Saved to <comparison_dir>/index/<keyword>.md

Usage:
  python -X utf8 scripts/search_sections.py "software sequence"
"""

import sys
import os
import re
import json
import zipfile
from pathlib import Path
from lxml import etree

from common import W, NS, parse_toc, build_style_map, sort_key

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / 'doc'


def _resolve_docx_and_out():
    """Get base docx path, output directory, and acronyms from config."""
    try:
        from config import load_config
        cfg = load_config()
        return cfg.base.docx, cfg.comparison_dir / 'index', cfg
    except (FileNotFoundError, ImportError):
        print('Error: config not found. Run init_config.py first.', file=sys.stderr)
        sys.exit(1)


def _load_acronyms(cfg) -> dict[str, str]:
    """Load acronyms.json from the base index if available."""
    acr_path = cfg.base.index_dir / 'acronyms.json'
    if acr_path.exists():
        with open(acr_path, encoding='utf-8') as f:
            return json.load(f)
    return {}


def _expand_query(query_words: list[str],
                  acronyms: dict[str, str]) -> list[str]:
    """Expand query words bidirectionally using the acronym dictionary.

    - Acronym → definition: searching 'UAJ' also matches 'Universal Audio Jack'
    - Definition → acronym: searching 'Universal Audio Jack' also matches 'UAJ'
    """
    expanded: set[str] = set(query_words)
    for word in query_words:
        w_upper = word.upper()
        # Acronym → definition words
        if w_upper in acronyms:
            expanded.update(tokenize(acronyms[w_upper]))
        # Definition words → acronym
        for acr, defn in acronyms.items():
            if word.lower() in set(tokenize(defn)):
                expanded.add(acr.lower())
    return list(expanded)


def tokenize(text):
    return re.sub(r'[^\w\s]', ' ', text.lower()).split()


def word_match(qw, tw):
    """Check if query word matches a text word, with prefix support.

    Exact match always returns True.  For words of 4+ characters, prefix
    matching is allowed (e.g. "sequen" matches "sequence").  Short words
    (< 4 chars) require exact match only — this avoids noisy substring hits.
    """
    if qw == tw:
        return True
    if len(qw) >= 4 and len(tw) >= 4:
        if tw.startswith(qw) or qw.startswith(tw):
            return True
    return False


def all_words_match(query_words, text, acronyms=None):
    """Check if ALL query words (or their acronym synonyms) match in text."""
    text_words = tokenize(text)
    if acronyms is None:
        acronyms = {}
    for qw in query_words:
        # Build candidate set: the word itself + any acronym synonyms
        candidates = {qw}
        w_upper = qw.upper()
        if w_upper in acronyms:
            candidates.update(tokenize(acronyms[w_upper]))
        for acr, defn in acronyms.items():
            if qw.lower() in set(tokenize(defn)):
                candidates.add(acr.lower())
        # At least one candidate must match
        if not any(any(word_match(c, tw) for tw in text_words) for c in candidates):
            return False
    return True


def count_matches(query_words, text, acronyms=None):
    """Count word matches including acronym synonyms."""
    text_words = tokenize(text)
    if acronyms is None:
        acronyms = {}
    expanded = set(query_words)
    for qw in query_words:
        w_upper = qw.upper()
        if w_upper in acronyms:
            expanded.update(tokenize(acronyms[w_upper]))
        for acr, defn in acronyms.items():
            if qw.lower() in set(tokenize(defn)):
                expanded.add(acr.lower())
    return sum(1 for tw in text_words
               for qw in expanded if word_match(qw, tw))


# ── Document parsing ───────────────────────────────────────────────────────

def para_text(p_elem):
    parts = []
    for t in p_elem.iter(f'{{{W}}}t'):
        if t.text:
            parts.append(t.text)
    return ''.join(parts)


# ── Search ──────────────────────────────────────────────────────────────────

def search(keyword, docx_path, acronyms=None):
    query_words = tokenize(keyword)
    if not query_words:
        print('Error: empty query', file=sys.stderr)
        sys.exit(1)
    if acronyms is None:
        acronyms = {}

    z = zipfile.ZipFile(str(docx_path))
    styles_xml = z.read('word/styles.xml')
    style_map = build_style_map(styles_xml)
    doc_xml = z.read('word/document.xml')
    root = etree.fromstring(doc_xml)
    body = root.find(f'{{{W}}}body')

    num_to_heading, _ = parse_toc(doc_xml)

    # Find heading positions
    body_children = list(body)
    heading_positions = []
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
        text = para_text(child).strip()
        if not text:
            continue
        # Match to TOC heading
        h_norm = re.sub(r'^[\dA-Z\.]+\s*', '', text.lower().replace('–', '-').replace('—', '-')).strip()
        for num, heading in num_to_heading.items():
            nh = re.sub(r'^[\dA-Z\.]+\s*', '', heading.lower().replace('–', '-').replace('—', '-')).strip()
            if nh == h_norm:
                heading_positions.append((idx, num, text, lvl))
                break

    section_to_pos = {hp[1]: i for i, hp in enumerate(heading_positions)}

    # For each section in TOC, collect body text and count matches
    all_nums = sorted(num_to_heading.keys(), key=sort_key)
    results = []

    for section_num in all_nums:
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

        all_text = heading_text + ' '
        for i in range(child_idx + 1, end_idx):
            child = body_children[i]
            if child.tag == f'{{{W}}}p':
                text = para_text(child).strip()
                if text:
                    all_text += text + ' '
            elif child.tag == f'{{{W}}}tbl':
                for tc in child.iter(f'{{{W}}}tc'):
                    for p in tc.findall(f'{{{W}}}p'):
                        text = para_text(p).strip()
                        if text:
                            all_text += text + ' '

        if not all_words_match(query_words, all_text, acronyms):
            continue

        match_count = count_matches(query_words, all_text, acronyms)
        results.append((section_num, heading_text, target_level, match_count))

    results.sort(key=lambda x: sort_key(x[0]))
    return results, keyword


# ── Output ──────────────────────────────────────────────────────────────────

def render(results, keyword):
    lines = []
    lines.append(f'## Search results for "{keyword}"')
    lines.append('')
    lines.append(f'{len(results)} sections found in base docx body text.')
    lines.append('')
    lines.append(f'| Compare? | Section | Heading | Matches |')
    lines.append(f'|-----------|---------|---------|---------|')

    for num, heading, level, count in results:
        indent = '  ' * level
        lines.append(f'| ✓ | {num} | {indent}{heading} | {count} |')

    out = '\n'.join(lines) + '\n'
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    docx_path, out_dir, cfg = _resolve_docx_and_out()
    acronyms = _load_acronyms(cfg)
    keyword = sys.argv[1]
    results, kw = search(keyword, docx_path, acronyms)

    output = render(results, kw)

    os.makedirs(str(out_dir), exist_ok=True)
    slug = re.sub(r'[^\w\s-]', '', keyword).strip().replace(' ', '_')
    out_path = out_dir / f'{slug}.md'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(output)

    print(output)
    print(f'Saved to {out_path}', file=sys.stderr)


if __name__ == '__main__':
    main()
