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
Build the combined section mapping between base and comparison versions.

Five passes; matching is one-to-one — every match consumes the comparison
section:

  1. Same-number exact heading match                        → 'same'
  2. Cross-number exact heading match                       → 'same'
     (multiple equal candidates: content score picks which one)
  2.5. Same-number fuzzy heading (head_sim >= 0.75)         → 'same'
     (no content gate — terminology renames lower content similarity)
  3. Fuzzy: heading similarity >= 0.75 gates candidacy; each candidate is
     scored  combined = 0.2 * whole-text trigram similarity
                      + 0.8 * opening-paragraphs trigram similarity.
     Best candidate over 0.6                                → 'same'
     otherwise                                              → 'new'
  4. Inspection: comparison sections never matched          → 'deleted';
     a 'new' base section with any matched descendant       → 'restructure'

Outputs full_mapping.json and full_mapping.md (review table) to
<comparison_dir>/index/.

Usage:
  python -X utf8 scripts/map_sections.py                       # build mapping
  python -X utf8 scripts/map_sections.py --id 5.11.3           # single-pair fingerprint report
  python -X utf8 scripts/map_sections.py --id 5.11.3 --comp-id 5.5.1
"""

import sys
import os
import re
import json
import argparse
from difflib import SequenceMatcher
from pathlib import Path

from common import (sort_key, collect_deep_headings, own_scope,
                    slice_heading_scope)

FUZZY_HEAD_THRESHOLD = 0.75
COMBINED_THRESHOLD = 0.6
TRIGRAM_WEIGHT = 0.2
OPENING_WEIGHT = 0.8

RECORD_FIELDS = ('base_num', 'base_heading', 'comp_num', 'comp_heading',
                 'head_sim', 'trigram_sim', 'opening_sim', 'combined_sim',
                 'kind')


def load_index(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def normalize(s):
    """Lowercase, collapse whitespace, strip punctuation for comparison."""
    s = s.lower().strip()
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s


def heading_similarity(h1, h2):
    """Return 0-1 similarity between two headings."""
    n1, n2 = normalize(h1), normalize(h2)
    if n1 == n2:
        return 1.0
    if n1 in n2 or n2 in n1:
        return 0.9
    return SequenceMatcher(None, n1, n2).ratio()


# ── content fingerprinting ──────────────────────────────────────────────────

def read_section_md(section_dir, num):
    """Find and read a section markdown file by number prefix."""
    pattern = f"{num}_"
    for f in sorted(os.listdir(section_dir)):
        if f.startswith(pattern) and f.endswith('.md'):
            with open(os.path.join(section_dir, f), encoding='utf-8') as fh:
                return fh.read()
    return None


def structural_fingerprint(text):
    """Count structural elements in markdown text."""
    own_lines = [l for l in text.split('\n') if not l.startswith('>')]
    own_text = '\n'.join(own_lines)

    return {
        'char_count': len(own_text),
        'word_count': len(own_text.split()),
        'heading_count': len(re.findall(r'^#{1,6}\s', own_text, re.MULTILINE)),
        'table_rows': len(re.findall(r'^\|.*\|$', own_text, re.MULTILINE)),
        'figures': len(re.findall(r'!\[.*?\]\(', own_text)),
        'numbered_items': len(re.findall(r'^\s*\d+\.\s', own_text, re.MULTILINE)),
        'bullet_items': len(re.findall(r'^\s*[-*]\s', own_text, re.MULTILINE)),
    }


def word_trigrams(text):
    """Word-trigram set of a text."""
    words = text.lower().split()
    return set(tuple(words[i:i+3]) for i in range(len(words) - 2))


def text_similarity(t1, t2):
    """Word-trigram similarity between two texts (0-1)."""
    return trigram_set_similarity(word_trigrams(t1), word_trigrams(t2))


def trigram_set_similarity(tg1, tg2):
    if not tg1 or not tg2:
        return 0.0
    return len(tg1 & tg2) / len(tg1 | tg2)


def first_paragraphs(text, n=3):
    """Extract first N non-empty, non-heading paragraphs."""
    paras = []
    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('>'):
            continue
        paras.append(stripped)
        if len(paras) >= n:
            break
    return '\n'.join(paras)


def content_fingerprint_compare(base_num, comp_num, base_sections_dir, comp_sections_dir):
    """Compare extracted content of two counterpart sections."""
    base_text = read_section_md(base_sections_dir, base_num)
    comp_text = read_section_md(comp_sections_dir, comp_num)

    if not base_text:
        return {'error': f'base section {base_num} not found in {base_sections_dir}'}
    if not comp_text:
        return {'error': f'comparison section {comp_num} not found in {comp_sections_dir}'}

    base_fp = structural_fingerprint(base_text)
    comp_fp = structural_fingerprint(comp_text)
    trigram_sim = round(text_similarity(base_text, comp_text), 3)
    first_para_sim = round(
        text_similarity(first_paragraphs(base_text), first_paragraphs(comp_text)), 3
    )

    deltas = {}
    for key in base_fp:
        d = base_fp[key] - comp_fp[key]
        if d != 0:
            deltas[key] = d

    return {
        'base_section': base_num,
        'comp_section': comp_num,
        'trigram_similarity': trigram_sim,
        'opening_paragraph_similarity': first_para_sim,
        'combined_similarity': round(
            TRIGRAM_WEIGHT * trigram_sim + OPENING_WEIGHT * first_para_sim, 3),
        'base_fingerprint': base_fp,
        'comp_fingerprint': comp_fp,
        'structural_delta': deltas,
    }


# ── combined mapping ────────────────────────────────────────────────────────

def build_mapping(base_idx, comp_idx, base_sections_dir, comp_sections_dir):
    """Run the 4-pass combined mapping. Returns records sorted by section number."""
    base_sections = base_idx['sections']
    comp_sections = comp_idx['sections']
    base_order = sorted(base_sections, key=sort_key)
    unmatched_comp = set(comp_sections)

    base_norm = {n: normalize(i['heading']) for n, i in base_sections.items()}
    comp_norm = {n: normalize(i['heading']) for n, i in comp_sections.items()}

    tri_cache = {}

    def _trigram_sets(side, sections_dir, num):
        key = (side, num)
        if key not in tri_cache:
            text = read_section_md(sections_dir, num)
            if not text:
                tri_cache[key] = (set(), set())
            else:
                tri_cache[key] = (word_trigrams(text),
                                  word_trigrams(first_paragraphs(text)))
        return tri_cache[key]

    def content_sims(bnum, cnum):
        b_full, b_open = _trigram_sets('base', base_sections_dir, bnum)
        c_full, c_open = _trigram_sets('comp', comp_sections_dir, cnum)
        tri = trigram_set_similarity(b_full, c_full)
        opn = trigram_set_similarity(b_open, c_open)
        comb = TRIGRAM_WEIGHT * tri + OPENING_WEIGHT * opn
        return round(tri, 3), round(opn, 3), round(comb, 3)

    records = {}

    def _record(bnum, cnum, head_sim, tri, opn, comb, kind):
        records[bnum] = {
            'base_num': bnum,
            'base_heading': base_sections[bnum]['heading'],
            'comp_num': cnum,
            'comp_heading': comp_sections[cnum]['heading'] if cnum else None,
            'head_sim': head_sim,
            'trigram_sim': tri,
            'opening_sim': opn,
            'combined_sim': comb,
            'kind': kind,
        }
        if cnum:
            unmatched_comp.discard(cnum)

    # Pass 1 — same-number exact heading
    for bnum in base_order:
        if bnum in unmatched_comp and base_norm[bnum] == comp_norm[bnum]:
            _record(bnum, bnum, 1.0, None, None, None, 'same')

    # Pass 2 — cross-number exact heading; content picks among multiple equals
    for bnum in base_order:
        if bnum in records:
            continue
        cands = [c for c in sorted(unmatched_comp, key=sort_key)
                 if comp_norm[c] == base_norm[bnum]]
        if not cands:
            continue
        if len(cands) == 1:
            _record(bnum, cands[0], 1.0, None, None, None, 'same')
        else:
            scored = [(content_sims(bnum, c), c) for c in cands]
            (tri, opn, comb), best = max(scored, key=lambda s: s[0][2])
            _record(bnum, best, 1.0, tri, opn, comb, 'same')

    # Pass 2.5 — same-number fuzzy heading: both sides unmatched at the
    # same number and head_sim >= 0.75.  Number + similar heading under
    # the shared numbering is decisive; no content gate, because
    # systematic terminology renames (e.g. NDAI_* → External_*) lower
    # content similarity exactly when the heading is fuzzy.
    for bnum in base_order:
        if bnum in records or bnum not in unmatched_comp:
            continue
        hs = heading_similarity(base_sections[bnum]['heading'],
                                comp_sections[bnum]['heading'])
        if hs >= FUZZY_HEAD_THRESHOLD:
            tri, opn, comb = content_sims(bnum, bnum)
            _record(bnum, bnum, round(hs, 3), tri, opn, comb, 'same')

    # Pass 3 — fuzzy heading gate + weighted content score
    for bnum in base_order:
        if bnum in records:
            continue
        best = None
        for cnum in sorted(unmatched_comp, key=sort_key):
            hs = heading_similarity(base_sections[bnum]['heading'],
                                    comp_sections[cnum]['heading'])
            if hs < FUZZY_HEAD_THRESHOLD:
                continue
            tri, opn, comb = content_sims(bnum, cnum)
            if best is None or comb > best[4]:
                best = (cnum, round(hs, 3), tri, opn, comb)
        if best and best[4] > COMBINED_THRESHOLD:
            _record(bnum, *best, 'same')
        else:
            _record(bnum, None, None, None, None, None, 'new')

    # Pass 4a — 'new' with any matched descendant → 'restructure'
    same_nums = [b for b, r in records.items() if r['kind'] == 'same']
    for bnum, r in records.items():
        if r['kind'] == 'new' and any(s.startswith(bnum + '.') for s in same_nums):
            r['kind'] = 'restructure'

    # Pass 4b — comparison sections never matched → 'deleted'.
    # A deleted comp number is only meaningful in comparison-document order,
    # so each deleted row is anchored after the row that matched its nearest
    # matched predecessor in comp order (not sorted as if it were a base num).
    deleted_head = []
    deleted_after = {}
    matched_comp = {r['comp_num'] for r in records.values() if r['comp_num']}
    last_matched = None
    for cnum in sorted(comp_sections, key=sort_key):
        if cnum in matched_comp:
            last_matched = cnum
            continue
        row = {
            'base_num': None,
            'base_heading': None,
            'comp_num': cnum,
            'comp_heading': comp_sections[cnum]['heading'],
            'head_sim': None,
            'trigram_sim': None,
            'opening_sim': None,
            'combined_sim': None,
            'kind': 'deleted',
        }
        if last_matched is None:
            deleted_head.append(row)
        else:
            deleted_after.setdefault(last_matched, []).append(row)

    results = list(deleted_head)
    for bnum in base_order:
        r = records[bnum]
        results.append(r)
        if r['comp_num'] in deleted_after:
            results.extend(deleted_after[r['comp_num']])
    return results


def write_mapping_md(results, path):
    """Write the mapping as a markdown review table."""
    def fmt(v):
        if v is None:
            return ''
        if isinstance(v, float):
            return f'{v:.3f}'
        return str(v).replace('|', '\\|')

    lines = [
        '| ' + ' | '.join(RECORD_FIELDS) + ' |',
        '|' + '---|' * len(RECORD_FIELDS),
    ]
    for r in results:
        lines.append('| ' + ' | '.join(fmt(r[k]) for k in RECORD_FIELDS) + ' |')
    with open(str(path), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


# ── deep mapping (####/##### pseudo-sections) ───────────────────────────────

def build_deep_mapping(section_rows, base_secs, comp_secs,
                       base_sections_dir, comp_sections_dir,
                       forced_pairs=None):
    """Map deep headings (####/#####) one-to-one, after the section pass.

    Node pools: all deep headings on both sides, plus leftover sections
    (base 'new'/'restructure', comp 'deleted') as cross-granularity
    candidates.  *forced_pairs* (from map_fixups) are pre-seeded before any
    pass and marked with fixup=True.  Passes:
      D1  same-scope exact heading (parents are a mapped pair) — ungated:
          a single candidate matches outright; multiple candidates are
          resolved by content score (content decides WHICH, not WHETHER)
      D2  global exact heading (cross-section / cross-granularity), gate >= 0.6
      D3  fuzzy: head_sim >= 0.75 gates candidacy, combined > 0.6 wins
      D4  elimination: exactly one unmatched child each side under a matched
          container pair -> pair, no content gate
      D5  leftovers: base -> new (restructure if matched descendants),
          comp -> deleted
    """
    sec_pair = {r['base_num']: r['comp_num'] for r in section_rows
                if r['base_num'] and r['comp_num']}
    leftover_base_secs = [r['base_num'] for r in section_rows
                          if r['base_num'] and r['kind'] in ('new', 'restructure')]
    leftover_comp_secs = [r['comp_num'] for r in section_rows
                          if not r['base_num'] and r['kind'] == 'deleted']

    bdeep = collect_deep_headings(base_sections_dir, base_secs)
    cdeep = collect_deep_headings(comp_sections_dir, comp_secs)

    def _nodes(deep, leftover_nums, secs):
        nodes = {d['id']: dict(d, section=False) for d in deep}
        for num in leftover_nums:
            nodes[num] = {'id': num, 'section': True, 'parent': num,
                          'container': None, 'path': None,
                          'heading': secs[num]['heading'],
                          'hashes': None, 'occurrence': 1, 'order': -1}
        return nodes

    bnodes = _nodes(bdeep, leftover_base_secs, base_secs)
    cnodes = _nodes(cdeep, leftover_comp_secs, comp_secs)

    scope_cache: dict[tuple, str] = {}

    def node_text(side, node):
        key = (side, node['id'])
        if key not in scope_cache:
            sdir, secs = ((base_sections_dir, base_secs) if side == 'b'
                          else (comp_sections_dir, comp_secs))
            parent_text = read_section_md(sdir, node['parent'])
            if parent_text is None:
                scope_cache[key] = ''
            elif node['section']:
                scope_cache[key] = own_scope(parent_text, secs, node['id'])
            else:
                scope = slice_heading_scope(
                    own_scope(parent_text, secs, node['parent']),
                    node['path'], node['hashes'], node['occurrence'])
                scope_cache[key] = scope or ''
        return scope_cache[key]

    tri_cache: dict[tuple, tuple] = {}

    def _tris(side, node):
        key = (side, node['id'])
        if key not in tri_cache:
            text = node_text(side, node)
            tri_cache[key] = (word_trigrams(text),
                              word_trigrams(first_paragraphs(text)))
        return tri_cache[key]

    def content_sims(bnode, cnode):
        bf, bo = _tris('b', bnode)
        cf, co = _tris('c', cnode)
        tri = trigram_set_similarity(bf, cf)
        opn = trigram_set_similarity(bo, co)
        return round(tri, 3), round(opn, 3), round(
            TRIGRAM_WEIGHT * tri + OPENING_WEIGHT * opn, 3)

    records: dict[str, dict] = {}
    comp_matched: set[str] = set()

    def _record(bid, cid, hs, tri, opn, comb, kind):
        records[bid] = {
            'base_num': bid,
            'base_heading': bnodes[bid]['heading'] if bid else None,
            'comp_num': cid,
            'comp_heading': cnodes[cid]['heading'] if cid else None,
            'head_sim': hs, 'trigram_sim': tri,
            'opening_sim': opn, 'combined_sim': comb,
            'kind': kind,
        }
        if cid:
            comp_matched.add(cid)

    def _base_order(nid):
        n = bnodes[nid]
        return (sort_key(n['parent']), n['order'])

    base_ids = sorted(bnodes, key=_base_order)

    # D0 — forced pairs from map_fixups (pre-seeded, marked fixup=True)
    for bid, cid in (forced_pairs or []):
        b, c = bnodes[bid], cnodes[cid]
        tri, opn, comb = content_sims(b, c)
        hs = round(heading_similarity(b['heading'], c['heading']), 3)
        _record(bid, cid, hs, tri, opn, comb, 'same')
        records[bid]['fixup'] = True

    # Matching passes (D1-D4), stabilized: every new match creates a new
    # container pair, which can unlock further scoped matches — so after
    # any match the loop restarts from the highest-priority pass.
    #
    #   D1  scoped exact heading (comp candidate lives under the matched
    #       counterpart of the base node's container) — ungated; content
    #       picks among multiple candidates
    #   D2  scoped fuzzy (same container scoping): head_sim >= 0.75,
    #       combined > 0.6
    #   D3  cross-granularity global (at least one side is a section):
    #       exact heading or fuzzy, gate >= 0.6.  Deep↔deep must never
    #       match globally, or scaffolds under consumed comp sections leak
    #   D4  elimination: exactly one unmatched child each side under a
    #       matched container pair, gated at combined >= 0.40

    def _container_map():
        pairs = dict(sec_pair)
        for bid, r in records.items():
            if r['kind'] == 'same':
                pairs[bid] = r['comp_num']
        return pairs

    def _open_by_container():
        c_open: dict[str, list[str]] = {}
        for c in cdeep:
            if c['id'] not in comp_matched:
                c_open.setdefault(c['container'], []).append(c['id'])
        return c_open

    def _scoped(exact):
        pairs = _container_map()
        c_open = _open_by_container()
        for bid in base_ids:
            b = bnodes[bid]
            if bid in records or b['section']:
                continue
            cc = pairs.get(b['container'])
            if cc is None:
                continue
            best = None
            for cid in c_open.get(cc, []):
                c = cnodes[cid]
                if exact:
                    if normalize(c['heading']) != normalize(b['heading']):
                        continue
                    hs = 1.0
                else:
                    hs = round(heading_similarity(b['heading'], c['heading']), 3)
                    if hs < FUZZY_HEAD_THRESHOLD:
                        continue
                tri, opn, comb = content_sims(b, c)
                if best is None or comb > best[4]:
                    best = (cid, hs, tri, opn, comb)
            if best and (exact or best[4] > COMBINED_THRESHOLD):
                _record(bid, best[0], best[1], best[2], best[3], best[4], 'same')
                return True
        return False

    def _scoped_content():
        # Renamed headings with near-identical content: within a matched
        # container pair, very high content similarity alone decides
        # (heading gate would reject the rename).
        pairs = _container_map()
        c_open = _open_by_container()
        for bid in base_ids:
            b = bnodes[bid]
            if bid in records or b['section']:
                continue
            cc = pairs.get(b['container'])
            if cc is None:
                continue
            best = None
            for cid in c_open.get(cc, []):
                tri, opn, comb = content_sims(b, cnodes[cid])
                if best is None or comb > best[4]:
                    hs = round(heading_similarity(b['heading'],
                                                  cnodes[cid]['heading']), 3)
                    best = (cid, hs, tri, opn, comb)
            if best and best[4] >= 0.75:
                _record(bid, best[0], best[1], best[2], best[3], best[4], 'same')
                return True
        return False

    def _cross_granularity():
        for bid in base_ids:
            if bid in records:
                continue
            b = bnodes[bid]
            best = None
            for cid, c in cnodes.items():
                if cid in comp_matched:
                    continue
                if not b['section'] and not c['section']:
                    continue
                if normalize(c['heading']) == normalize(b['heading']):
                    hs = 1.0
                else:
                    hs = round(heading_similarity(b['heading'], c['heading']), 3)
                    if hs < FUZZY_HEAD_THRESHOLD:
                        continue
                tri, opn, comb = content_sims(b, c)
                if best is None or comb > best[4]:
                    best = (cid, hs, tri, opn, comb)
            if best and best[4] >= COMBINED_THRESHOLD:
                _record(bid, best[0], best[1], best[2], best[3], best[4], 'same')
                return True
        return False

    def _elimination():
        pairs = _container_map()
        c_open = _open_by_container()
        b_open: dict[str, list[str]] = {}
        for bid in base_ids:
            b = bnodes[bid]
            if bid not in records and not b['section']:
                b_open.setdefault(b['container'], []).append(bid)
        for bc, cc in pairs.items():
            bs, cs = b_open.get(bc, []), c_open.get(cc, [])
            if len(bs) == 1 and len(cs) == 1:
                b, c = bnodes[bs[0]], cnodes[cs[0]]
                tri, opn, comb = content_sims(b, c)
                if comb < 0.40:
                    continue
                hs = round(heading_similarity(b['heading'], c['heading']), 3)
                _record(bs[0], cs[0], hs, tri, opn, comb, 'same')
                return True
        return False

    while (_scoped(exact=True) or _scoped(exact=False) or _scoped_content()
           or _cross_granularity() or _elimination()):
        pass

    # D5 — leftovers
    same_pseudo = [bid for bid, r in records.items()
                   if r['kind'] == 'same' and not bnodes[bid]['section']]
    for bid in base_ids:
        if bid in records or bnodes[bid]['section']:
            continue
        kind = ('restructure'
                if any(s.startswith(bid + '#') for s in same_pseudo)
                else 'new')
        _record(bid, None, None, None, None, None, kind)

    # Assemble rows: base rows in document order, deleted comp pseudos
    # threaded after their nearest matched comp predecessor.
    deleted_head, deleted_after = [], {}
    last_matched = None
    for c in cdeep:
        if c['id'] in comp_matched:
            last_matched = c['id']
            continue
        drow = {'base_num': None, 'base_heading': None,
                'comp_num': c['id'], 'comp_heading': c['heading'],
                'head_sim': None, 'trigram_sim': None,
                'opening_sim': None, 'combined_sim': None,
                'kind': 'deleted'}
        if last_matched is None:
            deleted_head.append(drow)
        else:
            deleted_after.setdefault(last_matched, []).append(drow)

    results = list(deleted_head)
    for bid in base_ids:
        if bid not in records:
            continue
        r = records[bid]
        results.append(r)
        if r['comp_num'] in deleted_after:
            results.extend(deleted_after[r['comp_num']])
    return results


# ── output formatting ──────────────────────────────────────────────────────

def print_content_report(cr):
    """Print a content fingerprint comparison report."""
    if 'error' in cr:
        print(f"ERROR: {cr['error']}")
        return

    print(f"Content comparison: base §{cr['base_section']}  vs  comparison §{cr['comp_section']}")
    print(f"  Trigram similarity:       {cr['trigram_similarity']}")
    print(f"  Opening paragraph sim:    {cr['opening_paragraph_similarity']}")
    print(f"  Combined (0.2/0.8):       {cr['combined_similarity']}")
    print()
    print(f"  {'Element':<25} {'base':>8} {'comparison':>8} {'Delta':>8}")
    print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8}")
    base_fp = cr['base_fingerprint']
    comp_fp = cr['comp_fingerprint']
    for key in base_fp:
        d = base_fp[key] - comp_fp[key]
        d_str = f"+{d}" if d > 0 else str(d)
        print(f"  {key:<25} {base_fp[key]:>8} {comp_fp[key]:>8} {d_str:>8}")


# ── main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Build the combined section mapping between base and comparison versions')
    parser.add_argument('--id', type=str, default=None,
                        help='Single-pair report: base section number')
    parser.add_argument('--comp-id', type=str, default=None,
                        help='Single-pair report: explicit comparison section number '
                             '(overrides mapping lookup)')
    args = parser.parse_args()

    try:
        from config import load_config
        cfg = load_config()
    except (FileNotFoundError, ImportError):
        print('Error: config not found. Run init_config.py first.', file=sys.stderr)
        sys.exit(1)

    base_idx = load_index(cfg.base.index_file)
    comp_idx = load_index(cfg.comparison.index_file)
    base_sections_dir = str(cfg.base.sections_dir)
    comp_sections_dir = str(cfg.comparison.sections_dir)

    if args.id:
        comp_num = args.comp_id
        if not comp_num:
            if not cfg.mapping_file.exists():
                print(f'ERROR: {cfg.mapping_file} not found. '
                      'Run map_sections.py without arguments first, or use --comp-id.')
                sys.exit(1)
            with open(cfg.mapping_file, encoding='utf-8') as f:
                mapping = json.load(f)
            for r in mapping:
                if r.get('base_num') == args.id:
                    comp_num = r.get('comp_num')
                    break
            if not comp_num:
                print(f'ERROR: No comparison counterpart mapped for {args.id}. '
                      'Use --comp-id to specify explicitly.')
                sys.exit(1)
        cr = content_fingerprint_compare(args.id, comp_num,
                                         base_sections_dir, comp_sections_dir)
        print_content_report(cr)
        return

    results = build_mapping(base_idx, comp_idx, base_sections_dir, comp_sections_dir)

    os.makedirs(str(cfg.mapping_file.parent), exist_ok=True)
    with open(str(cfg.mapping_file), 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    md_path = cfg.mapping_file.parent / 'full_mapping.md'
    write_mapping_md(results, md_path)

    kinds = {}
    for r in results:
        kinds[r['kind']] = kinds.get(r['kind'], 0) + 1
    print(f'{len(results)} mappings')
    print(f'Kinds: {kinds}')
    print(f'JSON: {cfg.mapping_file}')
    print(f'MD:   {md_path}')

    deep = build_deep_mapping(results, base_idx['sections'], comp_idx['sections'],
                              base_sections_dir, comp_sections_dir)
    deep_json = cfg.mapping_file.parent / 'deep_mapping.json'
    with open(str(deep_json), 'w', encoding='utf-8') as f:
        json.dump(deep, f, indent=2, ensure_ascii=False)
    deep_md = cfg.mapping_file.parent / 'deep_mapping.md'
    write_mapping_md(deep, deep_md)

    dkinds = {}
    for r in deep:
        dkinds[r['kind']] = dkinds.get(r['kind'], 0) + 1
    print(f'{len(deep)} deep mappings')
    print(f'Deep kinds: {dkinds}')
    print(f'JSON: {deep_json}')
    print(f'MD:   {deep_md}')


if __name__ == '__main__':
    main()
