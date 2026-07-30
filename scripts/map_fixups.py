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
Apply manual corrections to the section and deep mappings.

Each fixup forces a base ↔ comparison pair to 'same', overriding the
automatic mapping where the algorithm gets it wrong (e.g. a rewritten
introduction defeats the content-score gate). Discovered during manual
review of full_mapping.md / deep_mapping.md.

Entries whose ids contain '#' are DEEP fixups (pseudo-section ids like
'5.2.3#Transducer Power Domains in Smart Amp Functions'); they are applied
by rebuilding the deep mapping from the fixed section mapping with the
forced pairs pre-seeded.  Section fixups are applied to full_mapping as
before.  The deep mapping is ALWAYS rebuilt here, so it stays derived from
the fixed section mapping.

Rewrites full_mapping.json/md and deep_mapping.json/md, and writes a report
to <comparison_dir>/index/map_fixups.md.

map_sections.py regenerates both mappings from scratch, so re-run this
script after every mapping rebuild.

Usage:
  python -X utf8 scripts/map_fixups.py
"""

import sys
import os
import json



from config import load_config  # noqa: E402
from common import sort_key, collect_deep_headings  # noqa: E402
from map_sections import (  # noqa: E402
    heading_similarity, read_section_md, first_paragraphs, text_similarity,
    write_mapping_md, build_deep_mapping, TRIGRAM_WEIGHT, OPENING_WEIGHT,
)

# ── Fixup table ──────────────────────────────────────────────────────────────
# Keyed by (base_version, comp_version); only applied when the configured
# version pair matches. Each entry forces base_num ↔ comp_num to 'same':
#
#   {'base_num': '<num or pseudo id>', 'comp_num': '<num or pseudo id>',
#    'reason': '<why>'}
#
# Ids containing '#' are deep (pseudo-section) ids — see deep_mapping.md.
# Any pair the forced sections previously belonged to is broken (the
# displaced comparison node becomes 'deleted', the displaced base node
# becomes 'new'); 'restructure' and deleted-row threading are recomputed.

MAPPING_FIXUPS: dict[tuple[str, str], list[dict]] = {
    ('v1p2r17', 'v1p0'): [
        {
            'base_num': '5.7.3',
            'comp_num': '5.3.9',
            'reason': 'Introduction rewritten between versions; '
                      'table content essentially unchanged '
                      '(trigram 0.698, opening 0.31 → combined 0.388 < 0.6)',
        },
        {
            'base_num': '5.3.5',
            'comp_num': '5.2.3#Transducer Power Domains in Smart Amp Functions',
            'reason': 'Deep topic became its own section; heading reworded '
                      '(word order) so head_sim 0.57 < 0.75 and combined '
                      '0.569 just misses the 0.6 gate',
        },
        {
            'base_num': '4.16',
            'comp_num': '4.15',
            'reason': 'Heading renamed (DisCo for SoundWire Overview → '
                      'Discovery and Configuration Overview; head_sim 0.63) '
                      'and intro reworded (combined 0.49) — but the intro '
                      'text is near-parallel and all nine children already '
                      'map 4.16.x ↔ 4.15.x',
        },
        {
            'base_num': '5.4.1#Companion Amplifier Variant of Smart Amp (Deprecated)',
            'comp_num': '5.2.1#Companion Amplifier Variant of Smart Amp',
            'reason': 'v1.2 replaced the variant description with a '
                      'deprecation stub (combined 0.035) — pair anyway so '
                      'the old text shows next to the deprecation note',
        },
        {
            'base_num': '4.7.3#Effect of Reset on Function_Status Control',
            'comp_num': '4.7.3',
            'reason': 'v1.2 promoted the old §4.7.3 into a section-level '
                      'heading and added a new intro §4.7.3; the old content '
                      'now lives under the deep heading, pairing to the '
                      'now-deleted comp §4.7.3',
        },
    ],
}


def _is_deep(fx):
    return ('#' in (fx.get('base_num') or '')) or ('#' in (fx.get('comp_num') or ''))


def _content_sims(base_num, comp_num, base_sections_dir, comp_sections_dir):
    bt = read_section_md(base_sections_dir, base_num)
    ct = read_section_md(comp_sections_dir, comp_num)
    if not bt or not ct:
        return None, None, None
    tri = text_similarity(bt, ct)
    opn = text_similarity(first_paragraphs(bt), first_paragraphs(ct))
    comb = TRIGRAM_WEIGHT * tri + OPENING_WEIGHT * opn
    return round(tri, 3), round(opn, 3), round(comb, 3)


def apply_map_fixups(cfg):
    """Apply MAPPING_FIXUPS for the configured version pair.

    Returns (applied, already) entry lists (section fixups; deep fixups are
    always applied via the deep rebuild).
    """
    key = (cfg.base.version, cfg.comparison.version)
    fixups = MAPPING_FIXUPS.get(key, [])
    sec_fixups = [fx for fx in fixups if not _is_deep(fx)]
    deep_fixups = [fx for fx in fixups if _is_deep(fx)]

    with open(str(cfg.mapping_file), encoding='utf-8') as f:
        mapping = json.load(f)

    base_rows = {r['base_num']: r for r in mapping if r['base_num']}
    comp_heading = {r['comp_num']: r['comp_heading']
                    for r in mapping if r['comp_num']}
    comp_owner = {r['comp_num']: r['base_num']
                  for r in mapping if r['comp_num'] and r['base_num']}

    # Validation of section fixups — hard errors
    errors = []
    seen_base, seen_comp = set(), set()
    for fx in fixups:
        b, c = fx.get('base_num'), fx.get('comp_num')
        if b in seen_base:
            errors.append(f'base {b!r} used in multiple fixups')
        if c in seen_comp:
            errors.append(f'comparison {c!r} used in multiple fixups')
        seen_base.add(b)
        seen_comp.add(c)
    for fx in sec_fixups:
        b, c = fx.get('base_num'), fx.get('comp_num')
        if b not in base_rows:
            errors.append(f'base section {b!r} not found in mapping')
        if c not in comp_heading:
            errors.append(f'comparison section {c!r} not found in mapping')
    if errors:
        for e in errors:
            print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(1)

    base_sections_dir = str(cfg.base.sections_dir)
    comp_sections_dir = str(cfg.comparison.sections_dir)

    applied, already = [], []
    for fx in sec_fixups:
        b, c = fx['base_num'], fx['comp_num']
        row = base_rows[b]
        if row['comp_num'] == c and row['kind'] == 'same':
            already.append(fx)
            continue

        # Break the pair the comparison section currently belongs to
        owner = comp_owner.get(c)
        if owner and owner != b:
            other = base_rows[owner]
            other.update(comp_num=None, comp_heading=None, head_sim=None,
                         trigram_sim=None, opening_sim=None,
                         combined_sim=None, kind='new')
            del comp_owner[c]

        # The base row's previous comparison section becomes unmatched
        if row['comp_num'] and row['comp_num'] != c:
            comp_owner.pop(row['comp_num'], None)

        tri, opn, comb = _content_sims(b, c, base_sections_dir, comp_sections_dir)
        row.update(
            comp_num=c,
            comp_heading=comp_heading[c],
            head_sim=round(heading_similarity(row['base_heading'],
                                              comp_heading[c]), 3),
            trigram_sim=tri,
            opening_sim=opn,
            combined_sim=comb,
            kind='same',
            fixup=True,
        )
        comp_owner[c] = b
        applied.append(fx)

    # Recompute restructure: 'new' with any matched descendant
    same_nums = [b for b, r in base_rows.items() if r['kind'] == 'same']
    for b, r in base_rows.items():
        if r['kind'] in ('new', 'restructure'):
            r['kind'] = ('restructure'
                         if any(s.startswith(b + '.') for s in same_nums)
                         else 'new')

    # Rebuild rows: base order, deleted rows re-threaded in comp order
    base_order = sorted(base_rows, key=sort_key)
    matched = {r['comp_num'] for r in base_rows.values() if r['comp_num']}
    deleted_head, deleted_after = [], {}
    last_matched = None
    for cnum in sorted(comp_heading, key=sort_key):
        if cnum in matched:
            last_matched = cnum
            continue
        drow = {
            'base_num': None, 'base_heading': None,
            'comp_num': cnum, 'comp_heading': comp_heading[cnum],
            'head_sim': None, 'trigram_sim': None,
            'opening_sim': None, 'combined_sim': None,
            'kind': 'deleted',
        }
        if last_matched is None:
            deleted_head.append(drow)
        else:
            deleted_after.setdefault(last_matched, []).append(drow)

    results = list(deleted_head)
    for b in base_order:
        r = base_rows[b]
        results.append(r)
        if r['comp_num'] in deleted_after:
            results.extend(deleted_after[r['comp_num']])

    # Validate deep fixups against the FIXED section mapping
    base_secs = json.load(open(str(cfg.base.index_file), encoding='utf-8'))['sections']
    comp_secs = json.load(open(str(cfg.comparison.index_file), encoding='utf-8'))['sections']
    bdeep_ids = {d['id'] for d in
                 collect_deep_headings(cfg.base.sections_dir, base_secs)}
    cdeep_ids = {d['id'] for d in
                 collect_deep_headings(cfg.comparison.sections_dir, comp_secs)}
    leftover_b = {r['base_num'] for r in results
                  if r['base_num'] and r['kind'] in ('new', 'restructure')}
    leftover_c = {r['comp_num'] for r in results
                  if not r['base_num'] and r['kind'] == 'deleted'}
    for fx in deep_fixups:
        b, c = fx.get('base_num'), fx.get('comp_num')
        if b not in bdeep_ids and b not in leftover_b:
            errors.append(f'deep base id {b!r} not found (deep node or '
                          f'leftover base section)')
        if c not in cdeep_ids and c not in leftover_c:
            errors.append(f'deep comp id {c!r} not found (deep node or '
                          f'deleted comparison section)')
    if errors:
        for e in errors:
            print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(1)

    # Write fixed section mapping
    with open(str(cfg.mapping_file), 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    write_mapping_md(results, cfg.mapping_file.parent / 'full_mapping.md')

    # Rebuild the deep mapping from the fixed section mapping, with deep
    # forced pairs pre-seeded (D0)
    deep = build_deep_mapping(
        results, base_secs, comp_secs,
        base_sections_dir, comp_sections_dir,
        forced_pairs=[(fx['base_num'], fx['comp_num']) for fx in deep_fixups])
    deep_json = cfg.mapping_file.parent / 'deep_mapping.json'
    with open(str(deep_json), 'w', encoding='utf-8') as f:
        json.dump(deep, f, indent=2, ensure_ascii=False)
    write_mapping_md(deep, cfg.mapping_file.parent / 'deep_mapping.md')

    _write_report(cfg, sec_fixups, deep_fixups, applied, already)
    return applied, already


def _write_report(cfg, sec_fixups, deep_fixups, applied, already):
    """Write the fixup report to <comparison_dir>/index/map_fixups.md."""
    lines = ['# Mapping Fixup Report', '',
             '| base_num | comp_num | Table | Status | Reason |',
             '|---|---|---|---|---|']
    for fx in sec_fixups:
        if fx in applied:
            status = 'applied'
        elif fx in already:
            status = '*(already applied)*'
        else:
            status = '?'
        lines.append(f"| {fx['base_num']} | {fx['comp_num']} | section "
                     f"| {status} | {fx.get('reason', '')} |")
    for fx in deep_fixups:
        lines.append(f"| {fx['base_num']} | {fx['comp_num']} | deep "
                     f"| applied (rebuild) | {fx.get('reason', '')} |")
    lines.append('')

    report_path = cfg.mapping_file.parent / 'map_fixups.md'
    report_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'  Fixup report: {report_path}')


def main():
    cfg = load_config()
    if not cfg.mapping_file.exists():
        print(f'ERROR: {cfg.mapping_file} not found. Run map_sections.py first.',
              file=sys.stderr)
        sys.exit(1)

    key = (cfg.base.version, cfg.comparison.version)
    fixups = MAPPING_FIXUPS.get(key, [])
    if not fixups:
        print(f'No mapping fixups defined for {key[0]} vs {key[1]} — nothing to do.')
        return

    applied, already = apply_map_fixups(cfg)
    n_deep = sum(1 for fx in fixups if _is_deep(fx))
    print(f'{len(applied)} section fixup(s) applied, {len(already)} already '
          f'applied, {n_deep} deep fixup(s) applied via rebuild '
          f'({key[0]} vs {key[1]})')


if __name__ == '__main__':
    main()
