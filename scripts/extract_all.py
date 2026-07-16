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
Full extraction pipeline for both base and comparison versions.

Runs: extract_index → batch extract sections → map_sections (both modes).

Usage:
  python -X utf8 scripts/extract_all.py
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ''))

from config import load_config, ROOT
from common import get_logger
ROOT_PATH = Path(ROOT)
log = get_logger('extract_all')


def step_index(cfg):
    """Build master index for both versions."""
    from extract_index import build_index

    for label, ver in [('base', cfg.base), ('comparison', cfg.comparison)]:
        print(f'\n=== Building index for {label} ({ver.version}) ===')
        os.makedirs(str(ver.index_dir), exist_ok=True)
        index = build_index(str(ver.docx))
        with open(str(ver.index_file), 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        print(f'  Sections: {len(index["sections"])}')
        print(f'  Figures:  {len(index["figures"])}')
        print(f'  Tables:   {len(index["tables"])}')
        print(f'  Written to {ver.index_file.relative_to(ROOT_PATH)}')


def step_extract(cfg, no_clean=False):
    """Extract all sections for both versions.
    *no_clean*: skip removing old output directories (--no-clean)."""
    from extract_section import extract_sections

    for label, ver in [('base', cfg.base), ('comparison', cfg.comparison)]:
        print(f'\n=== Extracting {label} ({ver.version}) ===')
        if not no_clean:
            import shutil
            for d in [ver.sections_dir, ver.tables_dir, ver.images_dir]:
                if d.exists():
                    shutil.rmtree(str(d))
        for d in [ver.sections_dir, ver.tables_dir, ver.images_dir]:
            d.mkdir(parents=True, exist_ok=True)

        count = extract_sections(str(ver.docx), str(ver.output_dir), str(ver.index_file))
        print(f'  {count} sections extracted to {ver.sections_dir.relative_to(ROOT_PATH)}')


def step_fixups(cfg):
    """Apply known text corrections to extracted sections."""
    from extract_fixups import apply_fixups

    for label, ver in [('base', cfg.base), ('comparison', cfg.comparison)]:
        print(f'\n=== Applying fixups for {label} ({ver.version}) ===')
        count = apply_fixups(ver.output_dir, ver.version)
        print(f'  {count} file(s) modified')


def step_acronyms(cfg):
    """Extract acronyms from both versions and clean section 2.4."""
    from extract_acronyms import extract_acronyms, write_output

    for label, ver in [('base', cfg.base), ('comparison', cfg.comparison)]:
        print(f'\n=== Extracting acronyms for {label} ({ver.version}) ===')
        acronyms = extract_acronyms(str(ver.docx))
        if acronyms:
            write_output(acronyms, ver.sections_dir, ver.index_dir)
        else:
            print(f'  No acronyms found for {label}')


def step_map(cfg):
    """Run heading and content mode mapping."""
    from map_sections import build_heading_map, content_fingerprint_compare, load_index

    base_idx = load_index(str(cfg.base.index_file))
    comp_idx = load_index(str(cfg.comparison.index_file))

    print('\n=== Heading mode mapping (all sections) ===')
    results = build_heading_map(base_idx, comp_idx)

    mapping_path = cfg.mapping_file
    os.makedirs(str(mapping_path.parent), exist_ok=True)
    with open(str(mapping_path), 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    kinds = {}
    for r in results:
        kinds[r['kind']] = kinds.get(r['kind'], 0) + 1
    print(f'  {len(results)} mappings → {mapping_path.relative_to(ROOT_PATH)}')
    print(f'  Kinds: {kinds}')

    # Content fingerprinting for matched pairs
    print('\n=== Content mode mapping (matched pairs) ===')
    pairs = [(r['base_num'], r['comp_num'])
             for r in results if r.get('base_num') and r.get('comp_num')]

    base_sec_dir = str(cfg.base.sections_dir)
    comp_sec_dir = str(cfg.comparison.sections_dir)

    fp_results = []
    for i, (base_n, comp_n) in enumerate(pairs):
        cr = content_fingerprint_compare(base_n, comp_n, base_sec_dir, comp_sec_dir)
        fp_results.append(cr)
        if (i + 1) % 100 == 0:
            print(f'  {i+1}/{len(pairs)} done')

    fp_path = cfg.comparison_dir / 'index' / 'content_fingerprints.json'
    with open(str(fp_path), 'w', encoding='utf-8') as f:
        json.dump(fp_results, f, indent=2, ensure_ascii=False)

    verdicts = {}
    errs = 0
    for r in fp_results:
        if 'error' in r:
            errs += 1
        else:
            v = r.get('verdict', 'unknown')
            verdicts[v] = verdicts.get(v, 0) + 1
    print(f'  {len(fp_results)} pairs → {fp_path.relative_to(ROOT_PATH)}')
    print(f'  Verdicts: {verdicts}')
    if errs:
        print(f'  Errors: {errs}')


def main():
    # --no-clean: skip removing old output directories before extraction
    no_clean = '--no-clean' in sys.argv

    cfg = load_config()
    print(f'Base:       {cfg.base.version}  ({cfg.base.docx.relative_to(ROOT_PATH)})')
    print(f'Comparison: {cfg.comparison.version}  ({cfg.comparison.docx.relative_to(ROOT_PATH)})')
    print(f'Output:     {cfg.comparison_dir.relative_to(ROOT_PATH)}')
    if no_clean:
        print('(keeping existing output — --no-clean)')

    log.info('Starting full extraction pipeline')
    step_index(cfg)
    log.info('Index built')
    step_extract(cfg, no_clean=no_clean)
    log.info('Sections extracted')
    step_fixups(cfg)
    log.info('Fixups applied')
    step_acronyms(cfg)
    log.info('Acronyms extracted')
    step_map(cfg)
    log.info('Mapping complete')

    print('\n=== Extraction complete ===')


if __name__ == '__main__':
    main()
