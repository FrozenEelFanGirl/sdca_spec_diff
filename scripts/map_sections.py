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
Build a verified mapping between base and comparison sections.

Modes:
  --mode heading   Compare index headings, output mapping table (pre-extraction)
  --mode content   Compare extracted content fingerprints (post-extraction)

Heading mode outputs a mapping JSON that can drive batch extraction.
Content mode verifies an already-extracted pair matches by structure + text.

Examples:
  python -X utf8 scripts/map_sections.py --mode heading --filter UAJ
  python -X utf8 scripts/map_sections.py --mode heading --output mapping_uaj.json
  python -X utf8 scripts/map_sections.py --mode content --id 5.11.3
"""

import sys
import os
import re
import json
import argparse
from difflib import SequenceMatcher
from pathlib import Path

from common import sort_key


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


def find_counterpart(h, comp_sections):
    """Find the best comparison match for a base heading. Returns (section_num, score)."""
    best_num, best_score = None, 0.0
    for num, info in comp_sections.items():
        score = heading_similarity(h, info['heading'])
        if score > best_score:
            best_score = score
            best_num = num
    return best_num, best_score


def build_heading_map(base_idx, comp_idx, filter_text=None):
    """Compare headings across both indexes, return mapping records."""
    base_sections = base_idx['sections']
    comp_sections = comp_idx['sections']
    matched_comp = set()
    results = []

    for base_num, base_info in sorted(base_sections.items(), key=lambda x: sort_key(x[0])):
        h_base = base_info['heading']
        if filter_text and filter_text.upper() not in h_base.upper():
            continue

        best_comp_num, score = find_counterpart(h_base, comp_sections)

        if score >= 0.95:
            kind = 'exact_match'
        elif score >= 0.75:
            kind = 'fuzzy_match'
        else:
            kind = 'new_section'
            best_comp_num = None

        if best_comp_num:
            matched_comp.add(best_comp_num)

        results.append({
            'base_num': base_num,
            'base_heading': h_base,
            'base_file': base_info['file'],
            'comp_num': best_comp_num,
            'comp_heading': comp_sections[best_comp_num]['heading'] if best_comp_num else None,
            'comp_file': comp_sections[best_comp_num]['file'] if best_comp_num else None,
            'similarity': round(score, 3),
            'kind': kind,
        })

    # Find comparison sections with no base counterpart (deleted/moved)
    for comp_num, comp_info in sorted(comp_sections.items(), key=lambda x: sort_key(x[0])):
        if filter_text and filter_text.upper() not in comp_info['heading'].upper():
            continue
        if comp_num not in matched_comp:
            results.append({
                'base_num': None,
                'base_heading': None,
                'base_file': None,
                'comp_num': comp_num,
                'comp_heading': comp_info['heading'],
                'comp_file': comp_info['file'],
                'similarity': None,
                'kind': 'deleted_in_base',
            })

    results.sort(key=lambda r: sort_key(r['base_num'] or r['comp_num'] or '999'))
    return results


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


def text_similarity(t1, t2):
    """Word-trigram similarity between two texts (0-1)."""
    def trigrams(text):
        words = text.lower().split()
        return set(tuple(words[i:i+3]) for i in range(len(words)-2))

    tg1, tg2 = trigrams(t1), trigrams(t2)
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
        'base_fingerprint': base_fp,
        'comp_fingerprint': comp_fp,
        'structural_delta': deltas,
        'verdict': _verdict(trigram_sim, first_para_sim, deltas),
    }


def _verdict(trigram_sim, first_para_sim, deltas):
    """Heuristic verdict on whether these sections are likely the same content."""
    if trigram_sim >= 0.7 and first_para_sim >= 0.7:
        return 'likely_match'
    if trigram_sim >= 0.5 or first_para_sim >= 0.5:
        return 'uncertain'
    return 'likely_mismatch'


# ── output formatting ──────────────────────────────────────────────────────

def print_heading_table(results):
    """Print a readable mapping table."""
    header = f"{'Kind':<22} {'base':<10} {'comparison':<10} {'Sim':<6} Heading"
    print(header)
    print('-' * min(120, len(header) + 20))

    for r in results:
        kind = r['kind']
        base_n = r['base_num'] or '-'
        comp_n = r['comp_num'] or '-'
        sim = f"{r['similarity']:.2f}" if r['similarity'] is not None else '-'
        heading = r['base_heading'] or r['comp_heading'] or '-'

        if kind == 'exact_match':
            prefix = '  [MATCH]'
        elif kind == 'fuzzy_match':
            prefix = f'  [FUZZY {sim}]'
        elif kind == 'new_section':
            prefix = '  [NEW]'
        elif kind == 'deleted_in_base':
            prefix = '  [DELETED]'
        else:
            prefix = '  [?]'

        print(f"{prefix:<22} {base_n:<10} {comp_n:<10} {sim:<6} {heading}")

    kinds = {}
    for r in results:
        kinds[r['kind']] = kinds.get(r['kind'], 0) + 1
    print(f"\nSummary: {kinds}")


def print_content_report(cr):
    """Print a content fingerprint comparison report."""
    if 'error' in cr:
        print(f"ERROR: {cr['error']}")
        return

    print(f"Content comparison: base §{cr['base_section']}  vs  comparison §{cr['comp_section']}")
    print(f"  Trigram similarity:       {cr['trigram_similarity']}")
    print(f"  Opening paragraph sim:    {cr['opening_paragraph_similarity']}")
    print(f"  Verdict:                  {cr['verdict']}")
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
    parser = argparse.ArgumentParser(description='Map and verify sections between base and comparison versions')
    parser.add_argument('--mode', choices=['heading', 'content'], default='heading',
                        help='heading: pre-extraction mapping (default); content: post-extraction fingerprint verify')
    parser.add_argument('--filter', type=str, default=None,
                        help='Filter by heading text (case-insensitive substring, e.g. UAJ)')
    parser.add_argument('--id', type=str, default=None,
                        help='For --mode content: base section number to verify (requires counterpart in heading map)')
    parser.add_argument('--comp-id', type=str, default=None,
                        help='For --mode content: explicit comparison section number (overrides heading-map lookup)')
    parser.add_argument('--output', type=str, default=None,
                        help='Save mapping as JSON (heading mode only)')

    args = parser.parse_args()

    # Resolve paths from config
    try:
        from config import load_config
        cfg = load_config()
        base_idx_path = cfg.base.index_file
        comp_idx_path = cfg.comparison.index_file
        base_sections_dir = cfg.base.sections_dir
        comp_sections_dir = cfg.comparison.sections_dir
    except (FileNotFoundError, ImportError):
        print('Error: config not found. Run init_config.py first.', file=sys.stderr)
        sys.exit(1)

    base_idx = load_index(base_idx_path)
    comp_idx = load_index(comp_idx_path)

    if args.mode == 'heading':
        results = build_heading_map(base_idx, comp_idx, args.filter)
        print_heading_table(results)
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"\nMapping saved to {args.output}")

    elif args.mode == 'content':
        if not args.id:
            print("ERROR: --id is required for --mode content (base section number)")
            sys.exit(1)

        comp_num = args.comp_id
        if not comp_num:
            results = build_heading_map(base_idx, comp_idx)
            for r in results:
                if r.get('base_num') == args.id:
                    comp_num = r.get('comp_num')
                    break
            if not comp_num:
                print(f"ERROR: Could not find comparison counterpart for {args.id}. Use --comp-id to specify explicitly.")
                sys.exit(1)

        cr = content_fingerprint_compare(args.id, comp_num, base_sections_dir, comp_sections_dir)
        print_content_report(cr)


if __name__ == '__main__':
    main()
