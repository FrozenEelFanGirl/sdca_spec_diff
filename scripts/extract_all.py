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

Runs: extract_index → batch extract sections (+count verification) →
fixups → acronyms.

Section mapping is a Stage 2 step — run scripts/map_sections.py afterwards.

Usage:
  python -X utf8 scripts/extract_all.py
"""

import sys
import os
import re
import json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ''))

from config import load_config, ROOT
from common import get_logger, sort_key
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


def _verify_sections(ver):
    """Verify section files on disk match the index, including exact
    filenames as recorded in the index 'file' fields; exit non-zero on
    mismatch."""
    with open(str(ver.index_file), 'r', encoding='utf-8') as f:
        sections = json.load(f)['sections']
    expected = {num: e['file'].rsplit('/', 1)[-1] for num, e in sections.items()}

    disk = {}
    for p in ver.sections_dir.glob('*.md'):
        m = re.match(r'^([^_]+)_', p.name)
        disk.setdefault(m.group(1) if m else p.name, []).append(p.name)

    missing, mismatched = [], []
    for num in sorted(expected, key=sort_key):
        actual = disk.get(num, [])
        if expected[num] in actual:
            continue
        if actual:
            mismatched.append((num, expected[num], actual[0]))
        else:
            missing.append(num)
    extra = sorted((n for n in disk if n not in expected), key=sort_key)

    if missing or extra or mismatched:
        n_files = sum(len(v) for v in disk.values())
        log.error(f'Section verification failed for {ver.version}: '
                  f'{n_files} file(s) vs {len(expected)} index section(s)')
        if missing:
            log.error(f'  In index but no file: {", ".join(missing)}')
        if extra:
            log.error(f'  File but not in index: {", ".join(extra)}')
        for num, want, got in mismatched:
            log.error(f'  §{num} filename mismatch: index records {want!r}, disk has {got!r}')
        sys.exit(1)
    print(f'  Verified: {len(disk)} section file(s) == {len(expected)} index '
          f'section(s), all filenames match')


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
        _verify_sections(ver)


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

    print('\n=== Extraction complete ===')
    print('Next (Stage 2): python -X utf8 scripts/map_sections.py')


if __name__ == '__main__':
    main()
