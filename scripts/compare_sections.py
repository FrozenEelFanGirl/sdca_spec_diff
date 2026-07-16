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
Generate interleaved comparison files from a search report.

Usage:
  python -X utf8 scripts/compare_sections.py <report.md>

Diff rules:
  - equal:             base as-is,  comp *Unchanged.*
  - index/spelling:    base as-is,  comp *Unchanged (besides ...)*
  - content changed:   base **bold**, comp **bold**
  - new (base only):   base **bold**, comp *New in this version*
  - deleted (comp only):            comp ~~strikethrough~~
"""

import sys
import os
import re
import json
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ''))

from config import load_config, ROOT
from common import SPELLING_VARIANTS, get_logger
from diff_images import diff_images

log = get_logger('compare_sections')


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers — classification
# ═══════════════════════════════════════════════════════════════════════════════

def _is_heading(block: str) -> bool:
    return bool(re.match(r'^#{1,6}\s', block))


def _is_list(block: str) -> bool:
    first = block.split('\n')[0]
    return bool(re.match(r'^\s*([-*] |\d+\.)', first))


def _is_table(block: str) -> bool:
    return block.startswith('|')



def _classify(block: str) -> str:
    """Return block category: heading / list / table / figure / paragraph."""
    if not block:
        return 'paragraph'
    if _is_heading(block):
        return 'heading'
    if _is_list(block):
        return 'list'
    if _is_table(block):
        return 'table'
    if block.startswith('!['):
        return 'figure'
    return 'paragraph'


def _strip_blockquotes(text: str) -> str:
    """Strip '> ' prefix and collapse consecutive blockquote lines into
    single paragraphs so notes don't get split into multiple blocks."""
    result: list[str] = []
    in_note = False
    for line in text.split('\n'):
        if line.startswith('> '):
            stripped = line[2:]
            if in_note:
                result[-1] = result[-1] + ' ' + stripped
            else:
                result.append(stripped)
                in_note = True
        else:
            result.append(line)
            in_note = False
    return '\n'.join(result)


def _split_blocks(text: str) -> list[str]:
    """Split markdown into logical blocks at blank lines and style transitions."""
    raw: list[list[str]] = []
    cur: list[str] = []
    for line in text.split('\n'):
        if not line.strip():
            if cur:
                raw.append(cur); cur = []
        else:
            cur.append(line)
    if cur:
        raw.append(cur)

    blocks: list[str] = []
    for group in raw:
        subs: list[list[str]] = []
        sub: list[str] = []
        prev: str | None = None
        for line in group:
            s = line.strip()
            if re.match(r'^#{1,6}\s', s):    kind = 'heading'
            elif re.match(r'^\s*\d+\.\s', s): kind = 'numbered'
            elif re.match(r'^\s*[-*]\s', s):  kind = 'bullet'
            elif s.startswith('>'):           kind = 'note'
            elif s.startswith('|'):           kind = 'table'
            elif s.startswith('```'):         kind = 'code'
            elif s.startswith('!['):          kind = 'image'
            else:                             kind = 'body'

            no_split = {'body', 'note'}
            if prev is not None and kind != prev and kind not in no_split:
                if sub: subs.append(sub); sub = []
            elif prev is not None and prev not in no_split and kind in no_split:
                if sub: subs.append(sub); sub = []
            sub.append(line); prev = kind
        if sub: subs.append(sub)
        for sg in subs:
            blocks.append('\n'.join(sg))
    return blocks


def _split_paragraphs(blocks: list[str]) -> list[str]:
    """Split body-paragraph blocks into individual paragraphs.

    Blocks that are not body paragraphs (headings, lists, tables, figures)
    are passed through unchanged.  Body-paragraph blocks are split on
    newlines so that every natural paragraph gets its own block for
    comparison.
    """
    result: list[str] = []
    for b in blocks:
        if (_is_heading(b) or _is_list(b) or _is_table(b)
                or b.startswith('![')):
            result.append(b)
        else:
            for para in b.split('\n'):
                if para.strip():
                    result.append(para.strip())
    return result


def _split_all(blocks: list[str]) -> list[str]:
    """Split body paragraphs into individual blocks.
    Lists and tables stay as whole blocks — per-item / per-row
    diffing is handled internally by _diff_list / _diff_table."""
    blocks = _split_paragraphs(blocks)
    return blocks


def _split_list_items(list_block: str) -> list[str]:
    """Split a list block into top-level items (sub-items stay attached)."""
    if not list_block.strip():
        return [list_block]
    lines = list_block.split('\n')
    item_re = re.compile(r'^(\s*)([-*]|\d+\.)\s')
    min_indent = None
    for line in lines:
        m = item_re.match(line)
        if m:
            indent = len(m.group(1))
            if min_indent is None or indent < min_indent:
                min_indent = indent
    if min_indent is None:
        return [list_block]
    splits = [i for i, line in enumerate(lines)
              if item_re.match(line) and len(item_re.match(line).group(1)) == min_indent]
    items = []
    for i, s in enumerate(splits):
        e = splits[i + 1] if i + 1 < len(splits) else len(lines)
        items.append('\n'.join(lines[s:e]))
    return items


def _split_all_numbered_items(list_block: str) -> list[str]:
    """Split a numbered list into all items at every indentation level."""
    if not list_block.strip():
        return []
    lines = list_block.split('\n')
    item_re = re.compile(r'^(\s*)\d+\.\s')
    splits = [i for i, line in enumerate(lines) if item_re.match(line)]
    if not splits:
        return []
    items = []
    for idx, s in enumerate(splits):
        e = splits[idx + 1] if idx + 1 < len(splits) else len(lines)
        items.append('\n'.join(lines[s:e]))
    return items


def _get_numbered_item_info(item_text: str) -> tuple[int, int] | None:
    """Return (indent, number) from a numbered list item's first line."""
    first_line = item_text.split('\n')[0]
    m = re.match(r'^(\s*)(\d+)\.\s', first_line)
    if m:
        return (len(m.group(1)), int(m.group(2)))
    return None


def _merge_split_numbered_lists(blocks: list[str]) -> list[str]:
    """Reassemble numbered list fragments that were split by intervening
    non-heading blocks (tables, figures, notes).

    Merge rule (numbered lists only, not bullet -/*):
      1. Find List A → intervening non-heading blocks → List B
      2. First item of List B: indentation = ML, number = M
      3. Last item in List A at indentation ML: number = N
      4. If N + 1 == M → merge, move intervening blocks to end
    Iterates until no more merges.
    """
    numbered_re = re.compile(r'^\s*\d+\.\s')

    def _is_numbered_list(block: str) -> bool:
        return bool(numbered_re.match(block.split('\n')[0]))

    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(blocks):
            if not _is_list(blocks[i]) or not _is_numbered_list(blocks[i]):
                i += 1
                continue

            # List A at index i — scan ahead for List B
            j = i + 1
            while j < len(blocks):
                bj = blocks[j]
                if _is_heading(bj):
                    break
                if _is_list(bj) and _is_numbered_list(bj):
                    # Found a numbered List B at j
                    b_items = _split_all_numbered_items(bj)
                    if not b_items:
                        break
                    b_info = _get_numbered_item_info(b_items[0])
                    if not b_info:
                        break
                    ml, m = b_info

                    # Find last item in List A at indentation == ml
                    a_items = _split_all_numbered_items(blocks[i])
                    n = None
                    for item in reversed(a_items):
                        info = _get_numbered_item_info(item)
                        if info and info[0] == ml:
                            n = info[1]
                            break

                    if n is not None and n + 1 == m:
                        # Merge: append List B items to List A,
                        # then remove List B.  Intervening blocks
                        # stay where they are — they're already
                        # after the merged list.
                        blocks[i] = blocks[i] + '\n' + blocks[j]
                        del blocks[j]
                        changed = True
                        break
                    else:
                        # Non-consecutive numbering — this is a genuinely
                        # different list, not a split fragment.  Do not
                        # scan past it for a later list that might match
                        # (out of scope — list fragments appear in order).
                        break
                j += 1

            if changed:
                break  # restart outer while
            i += 1
    return blocks


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers — normalization
# ═══════════════════════════════════════════════════════════════════════════════

def _normalize_block(block: str, apply_spelling: bool = True) -> str:
    # Normalize to lowercase, strip markdown syntax, then remove all
    # punctuation.  Removing punctuation reduces structural noise for
    # matching but can lose semantically meaningful differences
    # (e.g. "IEEE 802.11" becomes indistinguishable from "IEEE 80211"
    # in the rare case both appear in the same document).
    t = block.lower()
    t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\*\*([^*]+)\*\*', r'\1', t)
    t = re.sub(r'\*([^*]+)\*', r'\1', t)
    t = re.sub(r'!\[(.*?)\]\(.*?\)', r'\1', t)
    t = re.sub(r'[^\w\s]', '', t)
    if apply_spelling:
        words = [SPELLING_VARIANTS.get(w, w) for w in t.split()]
        t = ' '.join(words).strip()
    else:
        t = re.sub(r'\s+', ' ', t).strip()
    return t


def _normalize_indices(text: str) -> str:
    t = text
    t = re.sub(r'\[Table\s+\d+(?:\.\d+)?', '[Table @INDEX', t)
    t = re.sub(r'\[Figure\s+\d+(?:\.\d+)?', '[Figure @INDEX', t)
    t = re.sub(r'\[Section\s+[\d]+(?:\.[\d]+)*', '[Section @INDEX', t)
    t = re.sub(r'\*\*Table\s+\d+', '**Table @INDEX', t)
    t = re.sub(r'\*\*Figure\s+\d+', '**Figure @INDEX', t)
    t = re.sub(r'!\[Figure\s+\d+', '![Figure @INDEX', t)
    t = re.sub(r'\.\./images/Figure\d+\.png', '../images/Figure@INDEX.png', t)
    t = re.sub(r'\.\./tables/Table\d+\.md', '../tables/Table@INDEX.md', t)
    t = re.sub(r'\.\./sections/[\d]+(?:\.[\d]+)*_\w+\.md', '../sections/@INDEX.md', t)
    t = re.sub(r'\*Figure\s+\d+', '*Figure @INDEX', t)
    t = re.sub(r'\bTable\s+\d+', 'Table @INDEX', t)
    t = re.sub(r'\bFigure\s+\d+', 'Figure @INDEX', t)
    t = re.sub(r'\bSection\s+[\d]+(?:\.[\d]+)*', 'Section @INDEX', t)
    return t


def _classify_differences(base_text: str, comp_text: str) -> list[str]:
    base_full = _normalize_block(_normalize_indices(base_text))
    comp_full = _normalize_block(_normalize_indices(comp_text))
    if base_full != comp_full:
        return ['content']
    cats: list[str] = []
    if _normalize_block(base_text) != _normalize_block(comp_text):
        cats.append('index')
    if (_normalize_block(_normalize_indices(base_text), apply_spelling=False) !=
            _normalize_block(_normalize_indices(comp_text), apply_spelling=False)):
        cats.append('spelling')
    return cats


def _unchanged_label(categories: list[str]) -> str | None:
    if not categories or 'content' in categories:
        return None
    return 'Unchanged (besides ' + ', '.join(categories) + ')'


# ═══════════════════════════════════════════════════════════════════════════════
# Word-level diff
# ═══════════════════════════════════════════════════════════════════════════════

def _protect_urls(text: str) -> tuple[str, dict[str, str]]:
    """Replace markdown links/images with placeholders so word-level
    diffing never inserts ** or ~~ inside link syntax."""
    url_map: dict[str, str] = {}
    def _repl(m):
        key = f'@URL_{len(url_map)}'; url_map[key] = m.group(0); return key
    t = re.sub(r'!\[[^\]]*\]\([^)]+\)', _repl, text)
    t = re.sub(r'\[[^\]]*\]\([^)]+\)', _repl, t)
    return t, url_map


def _restore_urls(text: str, url_map: dict[str, str]) -> str:
    for key, orig in url_map.items():
        text = text.replace(key, orig)
    return text


def _diff_words(base_text: str, comp_text: str) -> tuple[str, str]:
    """Word-level diff.  Replace → bold both; delete → bold base; insert → strike comp."""
    bl = base_text.split('\n'); cl = comp_text.split('\n')
    if len(bl) > 1 or len(cl) > 1:
        bn = [_normalize_block(l) for l in bl]; cn = [_normalize_block(l) for l in cl]
        sm = SequenceMatcher(None, bn, cn)
        bo: list[str] = []; co: list[str] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                bo.extend(bl[i1:i2]); co.extend(cl[j1:j2])
            elif tag == 'replace':
                for k in range(max(i2 - i1, j2 - j1)):
                    bt = bl[i1 + k] if k < i2 - i1 else ''
                    ct = cl[j1 + k] if k < j2 - j1 else ''
                    if bt and ct: ab, ac = _diff_words(bt, ct); bo.append(ab); co.append(ac)
                    elif bt: bo.append('**' + bt + '**')
                    elif ct: co.append('~~' + ct + '~~')
            elif tag == 'delete':
                for k in range(i1, i2): bo.append('**' + bl[k] + '**')
            elif tag == 'insert':
                for k in range(j1, j2): co.append('~~' + cl[k] + '~~')
        return '\n'.join(bo), '\n'.join(co)

    bp, bu = _protect_urls(base_text); cp, cu = _protect_urls(comp_text)
    bw = re.findall(r'\S+', bp); cw = re.findall(r'\S+', cp)
    sm = SequenceMatcher(None, [w.lower() for w in bw], [w.lower() for w in cw])
    bp_: list[str] = []; cp_: list[str] = []

    def _strip_punct(w):
        return re.sub(r'[),;:.]+$', '', w).lower()

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            bp_.extend(bw[i1:i2]); cp_.extend(cw[j1:j2])
        elif tag == 'replace':
            # Word-by-word: only bold words that truly differ
            n = max(i2 - i1, j2 - j1)
            bp_sub = []; cp_sub = []
            for k in range(n):
                ba = bw[i1 + k] if k < i2 - i1 else ''
                ca = cw[j1 + k] if k < j2 - j1 else ''
                if not ba: cp_sub.append('~~' + ca + '~~')
                elif not ca: bp_sub.append('**' + ba + '**')
                elif _strip_punct(ba) == _strip_punct(ca):
                    bp_sub.append(ba); cp_sub.append(ca)
                else:
                    bp_sub.append('**' + ba + '**')
                    cp_sub.append('**' + ca + '**')
            bp_.append(' '.join(bp_sub))
            cp_.append(' '.join(cp_sub))
        elif tag == 'delete':
            bp_.append('**' + ' '.join(bw[i1:i2]) + '**')
        elif tag == 'insert':
            cp_.append('~~' + ' '.join(cw[j1:j2]) + '~~')
    return _restore_urls(' '.join(bp_), bu), _restore_urls(' '.join(cp_), cu)


# ═══════════════════════════════════════════════════════════════════════════════
# List diff
# ═══════════════════════════════════════════════════════════════════════════════

def _split_marker(item: str) -> tuple[str, str]:
    """Split a list item into (marker, content).  Marker includes indentation
    and a trailing space so that ``1.Text`` becomes ``1. Text``."""
    m = re.match(r'^(\s*(?:[-*] |\d+\. ))\s*(.*)', item, re.DOTALL)
    if m:
        return m.group(1), m.group(2)
    return '', item


def _diff_list(base_block: str, comp_block: str) -> tuple[list[str], list[str]]:
    """Per-item diff of two list blocks.  Returns (base_out, comp_out).

    - Same count: 1-to-1 pairing.
    - One side empty: the other bolded / struck-through; caller adds a
      single ``*New in this version*`` or ``**Removed**`` annotation.
    - Different counts (both non-empty): SequenceMatcher aligns items;
      gaps are filled with numbered ``*New in this version*`` (comp) or
      ``**Removed in this version**`` (base) placeholders."""
    bi = _split_list_items(base_block); ci = _split_list_items(comp_block)
    # _split_list_items returns [''] for empty input — normalize
    if len(bi) == 1 and not bi[0].strip(): bi = []
    if len(ci) == 1 and not ci[0].strip(): ci = []
    bo: list[str] = []; co: list[str] = []

    # All new (comp empty) — bold base items
    if not ci:
        for item in bi:
            bm, bt = _split_marker(item)
            bo.append(bm + '**' + bt + '**')
        return bo, []

    # All deleted (base empty) — strikethrough comp items, base gets
    # placeholders; caller adds single annotation
    if not bi:
        for item in ci:
            cm, ct = _split_marker(item)
            co.append(cm + '~~' + ct + '~~')
        return bo, co

    # Same count → 1-to-1
    if len(bi) == len(ci):
        for ba, ca in zip(bi, ci):
            cats = _classify_differences(ba, ca)
            if 'content' not in cats:
                bo.append(ba); co.append(ca)
            else:
                bm, bt = _split_marker(ba)
                cm, ct = _split_marker(ca)
                ab, ac = _diff_words(bt, ct)
                bo.append(bm + ab); co.append(cm + ac)
        return bo, co

    # Different counts → greedy matching: each comp item pairs with
    # the best unmatched base item above threshold.  Remaining items
    # get numbered placeholders in the base order.
    SIM_THRESHOLD = 0.30
    used_base: set[int] = set()
    pairs: list[tuple[int, int]] = []  # (base_idx, comp_idx)
    for j, c_item in enumerate(ci):
        best_i = -1; best_sim = 0.0
        cn2 = _normalize_block(c_item)
        for i, b_item in enumerate(bi):
            if i in used_base: continue
            s = _block_similarity(b_item, c_item)
            if s > best_sim:
                best_sim = s; best_i = i
        if best_sim >= SIM_THRESHOLD:
            pairs.append((best_i, j))
            used_base.add(best_i)
    # Sort by base index so output follows base order
    pairs.sort()
    # Also track unmatched comp items
    used_comp: set[int] = {j for _, j in pairs}

    # Build output walking through base items in order
    pi = 0  # index into pairs
    for i, b_item in enumerate(bi):
        if pi < len(pairs) and pairs[pi][0] == i:
            # This base item has a comp match
            j = pairs[pi][1]
            c_item = ci[j]
            cats = _classify_differences(b_item, c_item)
            if 'content' not in cats:
                bo.append(b_item); co.append(c_item)
            else:
                bm, bt = _split_marker(b_item)
                cm, ct = _split_marker(c_item)
                ab, ac = _diff_words(bt, ct)
                bo.append(bm + ab)
                co.append(bm + ac)
            pi += 1
        else:
            # No comp match — this base item is new
            bm, bt = _split_marker(b_item)
            bo.append(bm + '**' + bt + '**')
            co.append(bm + '*New in this version*')

    # Append comp-only items at the end (deleted from base)
    for j, c_item in enumerate(ci):
        if j not in used_comp:
            cm, ct = _split_marker(c_item)
            co.append(cm + '~~' + ct + '~~')
            bo.append(cm + '**Removed in this version**')
    return bo, co


# ═══════════════════════════════════════════════════════════════════════════════
# Table diff
# ═══════════════════════════════════════════════════════════════════════════════

def _diff_table(base_block: str, comp_block: str) -> tuple[list[str], list[str]]:
    """Per-cell diff of two tables expanded to max rows × max cols.

    When data-row counts match, rows are paired 1-to-1.
    When counts differ, SequenceMatcher finds the optimal alignment."""
    br = base_block.strip().split('\n'); cr = comp_block.strip().split('\n')

    def _sep(row):
        return bool(re.match(r'^\|[ |\-:]+\|$', row))

    def _cells(row):
        parts = row.split('|')
        if parts and parts[0].strip() == '': parts = parts[1:]
        if parts and parts[-1].strip() == '': parts = parts[:-1]
        return [c.strip() for c in parts]

    bg, cg = [], []
    bs, cs = set(), set()
    for i, r in enumerate(br):
        if _sep(r): bs.add(i)
        else: bg.append(_cells(r))
    for i, r in enumerate(cr):
        if _sep(r): cs.add(i)
        else: cg.append(_cells(r))

    if not cg:
        return [_rebuild([], br, bs)], []

    max_c = max((len(row) for row in bg + cg), default=0)
    for row in bg:
        while len(row) < max_c: row.append('')
    for row in cg:
        while len(row) < max_c: row.append('')

    def _rtext(row): return ' | '.join(row)
    bt = [_rtext(r) for r in bg]; ct = [_rtext(r) for r in cg]

    ab, ac = [], []
    if len(bg) == len(cg):
        # 1-to-1 row matching
        for b_row, c_row in zip(bg, cg):
            ab.append(list(b_row)); ac.append(list(c_row))
    else:
        bn = [_normalize_block(t) for t in bt]; cn = [_normalize_block(t) for t in ct]
        sm = SequenceMatcher(None, bn, cn)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                for k in range(i2 - i1):
                    ab.append(list(bg[i1 + k])); ac.append(list(cg[j1 + k]))
            elif tag == 'replace':
                n = min(i2 - i1, j2 - j1)
                for k in range(n):
                    ab.append(list(bg[i1 + k])); ac.append(list(cg[j1 + k]))
                for k in range(n, i2 - i1):
                    ab.append(list(bg[i1 + k])); ac.append(['__NEW__'] * max_c)
                for k in range(n, j2 - j1):
                    ab.append(['__DEL__'] * max_c); ac.append(list(cg[j1 + k]))
            elif tag == 'delete':
                for k in range(i2 - i1):
                    ab.append(list(bg[i1 + k])); ac.append(['__NEW__'] * max_c)
            elif tag == 'insert':
                for k in range(j2 - j1):
                    ab.append(['__DEL__'] * max_c); ac.append(list(cg[j1 + k]))

    # Reconstruct output with separator rows in proper positions
    def _rebuild(result_rows, orig_rows, sep_set):
        final = []; di = 0
        for i in range(len(orig_rows)):
            if i in sep_set: final.append(orig_rows[i])
            elif di < len(result_rows): final.append(result_rows[di]); di += 1
        while di < len(result_rows): final.append(result_rows[di]); di += 1
        if not any(_sep(r) for r in final) and final:
            final.insert(1, '|' + '|'.join(['---'] * max_c) + '|')
        return final

    bo_rows, co_rows = [], []
    for brow, crow in zip(ab, ac):
        if crow and crow[0] == '__NEW__':
            bo_rows.append('| ' + ' | '.join('**' + c + '**' for c in brow) + ' |')
            cc = ['**New in this version**'] + [''] * (max_c - 1)
            co_rows.append('| ' + ' | '.join(cc) + ' |')
        elif brow and brow[0] == '__DEL__':
            bc = ['**Removed in this version**'] + [''] * (max_c - 1)
            bo_rows.append('| ' + ' | '.join(bc) + ' |')
            # Per-cell strikethrough
            cc = []
            for c in crow:
                cc.append('~~' + c + '~~' if c else '')
            co_rows.append('| ' + ' | '.join(cc) + ' |')
        else:
            bcells, ccells = [], []
            for ci in range(max_c):
                b = brow[ci]; c = crow[ci]
                if b == c: bcells.append(b); ccells.append(c)
                elif not b and c: bcells.append(''); ccells.append('~~' + c + '~~')
                elif b and not c: bcells.append('**' + b + '**'); ccells.append('')
                else:
                    cats = _classify_differences(b, c)
                    if 'content' not in cats: bcells.append(b); ccells.append(c)
                    else:
                        abw, acw = _diff_words(b.strip(), c.strip())
                        bcells.append(abw); ccells.append(acw)
            bo_rows.append('| ' + ' | '.join(bcells) + ' |')
            co_rows.append('| ' + ' | '.join(ccells) + ' |')

    return (_rebuild(bo_rows, br, bs), _rebuild(co_rows, cr, cs))


# ═══════════════════════════════════════════════════════════════════════════════
# Image pixel-diff helper
# ═══════════════════════════════════════════════════════════════════════════════

def _compare_images(base_block: str, comp_block: str,
                    base_dir: Path, comp_dir: Path) -> str | None:
    """Pixel-diff two figure images.  Result is memoized — callers may
    invoke this multiple times for the same pair and only pay the cost once."""
    m1 = re.search(r'!\[Figure\s+(\d+)', base_block)
    m2 = re.search(r'!\[Figure\s+(\d+)', comp_block)
    if not m1 or not m2: return None
    p1 = base_dir / f'Figure{m1.group(1)}.png'
    p2 = comp_dir / f'Figure{m2.group(1)}.png'
    if not p1.exists() or not p2.exists(): return None
    ratio, _, _, _ = diff_images(str(p1), str(p2))
    return '*Changed (' + str(int(ratio)) + '% diff)*' if ratio >= 2.0 else '*Unchanged.*'


# Per-invocation image-diff cache so _compare_images is never called
# twice for the same (base_block, comp_block) pair within one section.
_img_diff_cache: dict[tuple[str, str], str | None] = {}


def _cached_compare_images(base_block: str, comp_block: str,
                           base_dir: Path, comp_dir: Path) -> str | None:
    key = (base_block, comp_block)
    if key not in _img_diff_cache:
        _img_diff_cache[key] = _compare_images(base_block, comp_block, base_dir, comp_dir)
    return _img_diff_cache[key]


# TODO: Extract _fuzzy_lookahead resynchronization logic (Manhattan distance
# search, lines ~960-980) into its own function so the four-tier fallback
# strategy (same-cat lookahead / reverse lookahead / Manhattan resync /
# salvage) is readable as a dispatch table rather than inline control flow.
#
# TODO: Extract the _emit closure into a small state-holder class (e.g.
# BlockEmitter) with .out, .label, and methods for each tag.  This would
# make the diff logic unit-testable independently of the output format.
#
# TODO: After the main matching loop, add a two-pass "salvage" phase:
# re-run similarity matching on remaining unmatched blocks before falling
# through to the all-NEW/all-DELETED emit.  Currently a single failed
# Manhattan resync emits every remaining block as NEW or DELETED.

# ═══════════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════════

class ComparisonLogger:
    """Per-section synchronous log."""

    def __init__(self, log_dir: Path):
        self._dir = log_dir; self._fp = None; self._idx = 0

    def start(self, filename: str, bc: int, cc: int) -> None:
        name = filename + '_comparison.log'
        os.makedirs(str(self._dir), exist_ok=True)
        self._fp = open(str(self._dir / name), 'w', encoding='utf-8')
        self._idx = 0
        self._w(f'§{filename}')
        self._w(f'base: {bc} blocks  comp: {cc} blocks')
        self._w('')

    def log(self, cat: str, verdict: str, base_preview: str,
            comp_preview: str = '') -> None:
        def _short(t):
            t = t.replace('\n', ' ').strip()
            return t[:90] + '...' if len(t) > 90 else t
        self._w(f'[{self._idx:3d}] {cat:<15} | {verdict:<11} | {_short(base_preview)}')
        if comp_preview:
            self._w(f'      {"comp":<15} | {"":<11} | {_short(comp_preview)}')
        self._idx += 1

    def end(self) -> None:
        if self._fp:
            self._w(''); self._w('OK'); self._fp.close(); self._fp = None

    def _w(self, line: str) -> None:
        if self._fp: self._fp.write(line + '\n'); self._fp.flush()


# ═══════════════════════════════════════════════════════════════════════════════
# Blockquote output helper
# ═══════════════════════════════════════════════════════════════════════════════

def _emit_comp(out: list[str], blocks: list[str], version: str = '') -> None:
    if version: out.append(f'> **{version}:**')
    if blocks and _is_list(blocks[0]): out.append('>')
    for b in blocks:
        for line in b.split('\n'): out.append(f'> {line}')
        out.append('>')


def _heading_sibling_counts(blocks: list[str]) -> list[int]:
    """For each heading, count siblings (same-level headings under the same
    parent).  Non-heading blocks get 0.  Returns a list parallel to *blocks*."""
    counts = [0] * len(blocks)
    hidxs = [(i, len(re.match(r'^(#+)', blocks[i]).group(1)))
             for i, b in enumerate(blocks) if _is_heading(b)]
    for pos, (idx, level) in enumerate(hidxs):
        # Find parent: nearest preceding heading with higher level
        start = 0
        for j in range(pos - 1, -1, -1):
            if hidxs[j][1] < level:
                start = hidxs[j][0]
                break
        # Find end: first heading with strictly higher level after all
        # siblings.  Using < (not <=) ensures the entire sibling group
        # is consumed, not just the first sibling.
        end = len(blocks)
        for j in range(pos, len(hidxs)):
            if hidxs[j][1] < level and hidxs[j][0] > idx:
                end = hidxs[j][0]
                break
        # Count same-level siblings in (start, end)
        count = sum(1 for j in range(pos, len(hidxs))
                    if hidxs[j][0] < end and hidxs[j][1] == level)
        counts[idx] = count
    return counts


# ═══════════════════════════════════════════════════════════════════════════════
# Central dispatch
# ═══════════════════════════════════════════════════════════════════════════════

def _block_similarity(a: str, b: str) -> float:
    """Trigram overlap between two normalized blocks (0-1), with word-Jaccard
    fallback for blocks too short to form trigrams.

    Index numbers (Table/Figure/Section) are normalized so they don't
    break alignment of structurally identical blocks."""
    na = _normalize_block(_normalize_indices(a))
    nb = _normalize_block(_normalize_indices(b))
    if na == nb:
        return 1.0

    def _tri(s):
        words = s.split()
        return set(tuple(words[i:i+3]) for i in range(len(words)-2))
    ta = _tri(na); tb = _tri(nb)

    if ta and tb:
        return len(ta & tb) / len(ta | tb)

    # Fall back to word Jaccard for texts too short for trigrams
    wa = set(na.split()); wb = set(nb.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _process_blocks(base_blocks: list[str], comp_blocks: list[str],
                    comp_version: str,
                    base_img_dir: Path | None,
                    comp_img_dir: Path | None,
                    log: ComparisonLogger | None) -> str:
    """Count-first matching (paragraphs, figures): equal-length runs are
    paired 1-to-1.  Lists and tables stay as whole blocks — _diff_list
    and _diff_table handle per-item / per-row comparison internally."""

    global _img_diff_cache
    _img_diff_cache = {}

    if not comp_blocks:
        return '\n\n'.join(base_blocks) + '\n'

    out: list[str] = []
    bi, ci = 0, 0
    blen, clen = len(base_blocks), len(comp_blocks)
    LOOKAHEAD = 8
    RESYNC_WINDOW = 15
    THRESHOLDS = {
        'heading':   0.85,
        'paragraph': 0.40,
        'list':      0.35,
        'table':     0.40,
        'figure':    0.70,
    }
    _label: str | None = None
    bsib = _heading_sibling_counts(base_blocks)
    csib = _heading_sibling_counts(comp_blocks)

    def _emit(tag, b, c):
        nonlocal out, _label
        cat = _classify(b or c)

        # Verdict
        v_label = None
        if tag == 'equal':
            verdict = 'equal'
        elif tag == 'new':
            verdict = 'new'
        elif tag == 'deleted':
            verdict = 'deleted'
        else:  # replace
            if _normalize_block(b) == _normalize_block(c):
                verdict = 'equal'
            else:
                cats = _classify_differences(b, c)
                v_label = _unchanged_label(cats)
                verdict = (v_label.replace('Unchanged (besides ', '')
                          .replace(')', '') if v_label else 'diff')
            if (cat == 'figure' and base_img_dir and comp_img_dir):
                pix = _cached_compare_images(b, c, base_img_dir, comp_img_dir)
                if pix and pix != '*Unchanged.*':
                    verdict = 'diff'
        _label = v_label

        # Log
        if log:
            if tag == 'deleted':
                log.log(cat, verdict, '', c)
            else:
                log.log(cat, verdict, b, c if c else '')

        # Emit
        if tag == 'equal':
            out.append(b)
            if cat == 'heading':
                out.append('')
            elif cat == 'figure' and base_img_dir and comp_img_dir and c:
                ann = _cached_compare_images(b, c, base_img_dir, comp_img_dir)
                _emit_comp(out, [ann or '*Unchanged.*'], comp_version)
            elif cat == 'list':
                out.append('')
                _emit_comp(out, ['*Unchanged.*'], comp_version)
            elif cat == 'table':
                out.append('')
                _emit_comp(out, ['*Unchanged.*'], comp_version)
            else:
                out.append('')
                _emit_comp(out, ['*Unchanged.*'], comp_version)

        elif tag == 'replace':
            if cat == 'heading':
                out.append(b); out.append('')
                _emit_comp(out, [c], comp_version)
            elif cat == 'list':
                bo, co = _diff_list(b, c)
                if bo: out.append('\n'.join(bo)); out.append('')
                if co: _emit_comp(out, ['\n'.join(co)], comp_version)
            elif cat == 'table':
                bo, co = _diff_table(b, c)
                if bo: out.append('\n'.join(bo)); out.append('')
                if co: _emit_comp(out, ['\n'.join(co)], comp_version)
            elif cat == 'figure':
                out.append(b); out.append('')
                if base_img_dir and comp_img_dir:
                    pix = _cached_compare_images(b, c, base_img_dir, comp_img_dir)
                    if pix and pix != '*Unchanged.*':
                        _emit_comp(out, [c, pix], comp_version)
                    elif _label:
                        _emit_comp(out, ['*' + _label + '*'], comp_version)
                    else:
                        _emit_comp(out, [c, pix or '*Unchanged.*'], comp_version)
                elif _label:
                    _emit_comp(out, ['*' + _label + '*'], comp_version)
                else:
                    _emit_comp(out, [c], comp_version)
            else:  # paragraph
                if _label:
                    out.append(b); out.append('')
                    _emit_comp(out, ['*' + _label + '*'], comp_version)
                else:
                    ab, ac = _diff_words(b, c)
                    out.append(ab); out.append('')
                    _emit_comp(out, [ac], comp_version)

        elif tag == 'new':
            if cat == 'heading':
                out.append(b); out.append('')
                _emit_comp(out, ['*New in this version*'], comp_version)
            elif cat == 'list':
                bo, _ = _diff_list(b, '')
                if bo: out.append('\n'.join(bo)); out.append('')
                _emit_comp(out, ['*New in this version*'], comp_version)
            elif cat == 'table':
                bo, _ = _diff_table(b, '')
                if bo: out.append('\n'.join(bo)); out.append('')
                _emit_comp(out, ['*New in this version*'], comp_version)
            else:
                for line in b.split('\n'):
                    out.append('**' + line + '**')
                out.append('')
                _emit_comp(out, ['*New in this version*'], comp_version)

        elif tag == 'deleted':
            if cat == 'list':
                bo, co = _diff_list('', c)
                if not bo:
                    # All-deleted — single annotation
                    out.append('**Removed in this version**')
                    out.append('')
                else:
                    out.append('\n'.join(bo)); out.append('')
                if co: _emit_comp(out, ['\n'.join(co)], comp_version)
                out.append('')
            elif cat == 'table':
                bo, co = _diff_table('', c)
                if co: _emit_comp(out, ['\n'.join(co)], comp_version)
                out.append('')
            else:
                lines = ['~~' + line + '~~' for line in c.split('\n')]
                _emit_comp(out, ['\n'.join(lines)], comp_version)
                out.append('')

    def _count_run(blocks, start, cat):
        n = 0
        for i in range(start, len(blocks)):
            if _classify(blocks[i]) == cat: n += 1
            else: break
        return n

    def _fuzzy_lookahead() -> bool:
        nonlocal bi, ci
        lt = THRESHOLDS.get(comp_cat, 0.40)
        for look in range(1, min(LOOKAHEAD, blen - bi)):
            if _classify(base_blocks[bi + look]) != comp_cat: continue
            if _block_similarity(base_blocks[bi + look],
                                 comp_blocks[ci]) >= lt:
                for i in range(bi, bi + look):
                    _emit('new', base_blocks[i], '')
                bi = bi + look
                return True
        lt = THRESHOLDS.get(base_cat, 0.40)
        for look in range(1, min(LOOKAHEAD, clen - ci)):
            if _classify(comp_blocks[ci + look]) != base_cat: continue
            if _block_similarity(base_blocks[bi],
                                 comp_blocks[ci + look]) >= lt:
                for j in range(ci, ci + look):
                    _emit('deleted', '', comp_blocks[j])
                ci = ci + look
                return True
        for dist in range(1, RESYNC_WINDOW + 1):
            for dx in range(dist + 1):
                dy = dist - dx
                bx2, cy2 = bi + dx, ci + dy
                if bx2 >= blen or cy2 >= clen: continue
                if dx == 0 and dy == 0: continue
                bc2 = _classify(base_blocks[bx2])
                cc2 = _classify(comp_blocks[cy2])
                if bc2 != cc2: continue
                th = THRESHOLDS.get(bc2, 0.40)
                if _block_similarity(base_blocks[bx2],
                                     comp_blocks[cy2]) >= th:
                    for i in range(bi, bx2):
                        _emit('new', base_blocks[i], '')
                    for j in range(ci, cy2):
                        _emit('deleted', '', comp_blocks[j])
                    bi, ci = bx2, cy2
                    return True
        for i in range(bi, blen):
            _emit('new', base_blocks[i], '')
        for j in range(ci, clen):
            _emit('deleted', '', comp_blocks[j])
        bi, ci = blen, clen
        return False

    while bi < blen or ci < clen:
        if bi >= blen:
            if ci < clen:
                out.append('**Removed in this version**')
                out.append('')
                out.append(f'> **{comp_version}:**')
                for j in range(ci, clen):
                    c = comp_blocks[j]
                    cat = _classify(c)
                    if cat == 'table':
                        _, co = _diff_table('', c)
                        for row in co:
                            for line in row.split('\n'):
                                out.append(f'> {line}')
                        out.append('>')
                    elif cat == 'list':
                        _, co = _diff_list('', c)
                        out.append('>')
                        for item in co:
                            for line in item.split('\n'):
                                out.append(f'> {line}')
                            out.append('>')
                    else:
                        for line in c.split('\n'):
                            out.append(f'> ~~{line}~~')
                        out.append('>')
            break
        if ci >= clen:
            for i in range(bi, blen):
                _emit('new', base_blocks[i], '')
            break

        base_cat = _classify(base_blocks[bi])
        comp_cat = _classify(comp_blocks[ci])

        if base_cat != comp_cat:
            _fuzzy_lookahead()
            continue

        # Count-first: equal-length runs of paragraphs / figures
        # (not headings — solitary by nature; not lists/tables — single
        # blocks whose internal counts are handled by _diff_list/_diff_table)
        if base_cat in ('paragraph', 'figure'):
            bc = _count_run(base_blocks, bi, base_cat)
            cc = _count_run(comp_blocks, ci, comp_cat)
            if bc == cc:
                for k in range(bc):
                    b_blk = base_blocks[bi + k]; c_blk = comp_blocks[ci + k]
                    tag = 'equal' if _normalize_block(b_blk) == _normalize_block(c_blk) else 'replace'
                    _emit(tag, b_blk, c_blk)
                bi += bc; ci += cc
                continue

        # Heading sibling-match
        if base_cat == 'heading':
            blv = len(re.match(r'^(#+)', base_blocks[bi]).group(1))
            clv = len(re.match(r'^(#+)', comp_blocks[ci]).group(1))
            if blv == clv and bsib[bi] > 0 and bsib[bi] == csib[ci]:
                b_blk = base_blocks[bi]; c_blk = comp_blocks[ci]
                tag = 'equal' if _normalize_block(b_blk) == _normalize_block(c_blk) else 'replace'
                _emit(tag, b_blk, c_blk)
                bi += 1; ci += 1
                continue

        # Similarity match
        sim = _block_similarity(base_blocks[bi], comp_blocks[ci])
        threshold = THRESHOLDS.get(base_cat, 0.40)
        if sim >= threshold:
            tag = 'equal' if _normalize_block(base_blocks[bi]) == _normalize_block(comp_blocks[ci]) else 'replace'
            _emit(tag, base_blocks[bi], comp_blocks[ci])
            bi += 1; ci += 1
            continue

        _fuzzy_lookahead()

    # Collapse blank-line runs
    result: list[str] = []
    blc = 0
    for line in out:
        if line == '' or line == '>':
            blc += 1
            if blc <= 2: result.append(line)
        else:
            blc = 0; result.append(line)
    return '\n'.join(result).strip() + '\n'


# ═══════════════════════════════════════════════════════════════════════════════
# Asset helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _rewrite_assets(text: str, bv: str, cv: str) -> str:
    result: list[str] = []
    for line in text.split('\n'):
        ver = cv if line.startswith('> ') else bv
        line = re.sub(r'(\.\./images/Figure\d+)(\.png)', rf'\1_{ver}\2', line)
        line = re.sub(r'(\.\./tables/Table\d+)(\.md)', rf'\1_{ver}\2', line)
        result.append(line)
    return '\n'.join(result)


def _copy_assets(text: str,
                 b_img: Path, b_tbl: Path,
                 c_img: Path, c_tbl: Path,
                 comp_dir: Path, bv: str, cv: str) -> None:
    import shutil
    for sub in ('images', 'tables'):
        (comp_dir / sub).mkdir(parents=True, exist_ok=True)

    def _cp(line, is_comp, kind, ext):
        ver = cv if is_comp else bv
        sd = (c_img if is_comp else b_img) if kind == 'images' else (c_tbl if is_comp else b_tbl)
        for m in re.finditer(rf'\.\./{kind}/(\w+)(\{ext})', line):
            name, suf = m.group(1), m.group(2)
            dest = comp_dir / kind / f'{name}_{ver}{suf}'
            if not dest.exists():
                src = sd / f'{name}{suf}'
                if src.exists(): shutil.copy2(str(src), str(dest))

    for line in text.split('\n'):
        _cp(line, line.startswith('> '), 'images', '.png')
        _cp(line, line.startswith('> '), 'tables', '.md')


# ═══════════════════════════════════════════════════════════════════════════════
# Build & main
# ═══════════════════════════════════════════════════════════════════════════════

def parse_report(report_path: Path) -> list[str]:
    with open(report_path, encoding='utf-8') as f:
        content = f.read()
    return [m.group(1) for m in re.finditer(r'\|\s*✓\s*\|\s*([\d.]+)\s*\|', content)]


def find_counterpart(num: str, mapping: list[dict]) -> dict | None:
    for m in mapping:
        if m.get('base_num') == num: return m
    return None


def read_section_file(sections_dir: Path, num: str) -> str | None:
    prefix = f'{num}_'
    for f in sorted(sections_dir.iterdir()):
        if f.name.startswith(prefix) and f.suffix == '.md':
            return f.read_text(encoding='utf-8')
    return None


def build_comparison(base_content: str, comp_num: str | None,
                     comp_heading: str | None, comp_content: str | None,
                     kind: str | None, comp_version: str = '',
                     base_img_dir: Path | None = None,
                     comp_img_dir: Path | None = None,
                     log: ComparisonLogger | None = None) -> str:
    lines: list[str] = []
    if kind == 'new_section' or comp_num is None:
        lines.append('> **New in this version**'); lines.append('>')
    elif kind == 'deleted_in_base':
        lines.append(f'> **Removed from this version (was comparison §{comp_num or "?"})**')
        lines.append('>')
    elif comp_num:
        lines.append(f'> **Mapped from comparison §{comp_num}**'); lines.append('>')
    lines.append('')

    if not comp_content:
        lines.append(base_content.strip())
        if comp_num:
            lines.append('')
            lines.append(f'> **Comparison §{comp_num}**'
                         f'{f" — {comp_heading}" if comp_heading else ""}')
            lines.append('>')
            lines.append('> *(Comparison section not yet extracted. Run extract_all.py first.)*')
            lines.append('>')
        return '\n'.join(lines) + '\n'

    base_content = _strip_blockquotes(base_content)
    comp_content = _strip_blockquotes(comp_content)
    base_blocks = _split_blocks(base_content)
    comp_blocks = _split_blocks(comp_content)

    # Split body paragraphs into individual blocks; lists and tables stay whole
    base_blocks = _split_all(base_blocks)
    comp_blocks = _split_all(comp_blocks)

    base_blocks = _merge_split_numbered_lists(base_blocks)
    comp_blocks = _merge_split_numbered_lists(comp_blocks)

    interleaved = _process_blocks(base_blocks, comp_blocks, comp_version,
                                  base_img_dir, comp_img_dir, log)
    lines.append(interleaved)
    lines.append('')
    lines.append(f'> **Comparison §{comp_num}**'
                 f'{f" — {comp_heading}" if comp_heading else ""}')
    lines.append('>')
    return '\n'.join(lines) + '\n'


def main():
    cfg = load_config()
    if not cfg.mapping_file.exists():
        log.error('Mapping file not found: %s', cfg.mapping_file)
        log.error('Run extract_all.py first to generate the mapping.')
        sys.exit(1)
    with open(cfg.mapping_file, encoding='utf-8') as f:
        mapping = json.load(f)

    if len(sys.argv) >= 2:
        rp = Path(sys.argv[1])
        if not rp.is_absolute(): rp = Path(ROOT) / rp
        section_nums = parse_report(rp)
        print(f'Parsed {len(section_nums)} checked sections from {rp.name}')
    else:
        section_nums = [m['base_num'] for m in mapping
                        if m.get('base_num') and m.get('kind') != 'deleted_in_base']
        print(f'Comparing all {len(section_nums)} mapped sections')

    if not section_nums:
        print('No sections to compare.'); return

    out_dir = cfg.comparison_dir / 'sections'
    os.makedirs(str(out_dir), exist_ok=True)

    created = 0
    log = ComparisonLogger(out_dir)
    for num in section_nums:
        bc = read_section_file(cfg.base.sections_dir, num)
        if bc is None:
            log.warning('SKIP §%s: not found in base sections', num); continue

        m = find_counterpart(num, mapping)
        cn = m['comp_num'] if m else None
        ch = m['comp_heading'] if m else None
        kd = m['kind'] if m else None
        cc = read_section_file(cfg.comparison.sections_dir, cn) if cn else None

        # Determine output filename first
        fn = None
        for f in cfg.base.sections_dir.iterdir():
            if f.name.startswith(f'{num}_') and f.suffix == '.md':
                fn = f.name.replace('.md', '_comparison.md'); break
        if fn is None: fn = f'{num}_comparison.md'

        log.start(fn.replace('_comparison.md', ''),
                  len(_split_blocks(bc)),
                  len(_split_blocks(cc)) if cc else 0)

        cv = cfg.comparison.version_display
        text = build_comparison(bc, cn, ch, cc, kd, cv,
                                base_img_dir=cfg.base.images_dir,
                                comp_img_dir=cfg.comparison.images_dir,
                                log=log)

        _copy_assets(text,
                     cfg.base.images_dir, cfg.base.tables_dir,
                     cfg.comparison.images_dir, cfg.comparison.tables_dir,
                     cfg.comparison_dir, cfg.base.version, cfg.comparison.version)
        text = _rewrite_assets(text, cfg.base.version, cfg.comparison.version)
        (out_dir / fn).write_text(text, encoding='utf-8')
        created += 1
        log.end()

    print(f'Created {created} comparison files in {out_dir.relative_to(Path(ROOT))}')


if __name__ == '__main__':
    main()
