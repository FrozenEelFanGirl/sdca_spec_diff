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
Apply known text corrections to extracted markdown sections.

Each fixup is an exact-string replacement pair discovered during manual
review of the extracted content.  Exact matching avoids collateral damage
in unrelated passages.

Usage:
  python -X utf8 scripts/extract_fixups.py --from-config [base|comp]
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from config import load_config

# ── Fixup table ──────────────────────────────────────────────────────────────
# Each entry is (exact_old_string, replacement_string).
# Only whole-text matches are replaced — no regex, no partial-word matching.

FIXUPS: list[tuple[str, str]] = [
    # em-dash → hyphen in specific property name
    (
        'mipi-sdca-function-topology—pipe',
        'mipi-sdca-function-topology-pipe',
    ),
    # Non-breaking space → regular space in captions
    (
        'Table\xa0',
        'Table ',
    ),
    (
        'Figure\xa0',
        'Figure ',
    ),
    (
        'Section\xa0',
        'Section ',
    ),
    # en-dash → hyphen in specific number ranges
    (
        '56–63',
        '56-63',
    ),
    # Spelling fixes from source document
    (
        'inisde',
        'inside',
    ),
]


def apply_fixups(output_dir: Path) -> int:
    """Apply all fixups to every .md file in *output_dir*/sections/.

    Returns the number of files modified.
    """
    sections_dir = output_dir / 'sections'
    if not sections_dir.is_dir():
        print(f'  Sections dir not found: {sections_dir}', file=sys.stderr)
        return 0

    modified = 0
    # Track which fixup (by index) affected which files
    hits: dict[int, list[str]] = {i: [] for i in range(len(FIXUPS))}

    for md_file in sorted(sections_dir.iterdir()):
        if md_file.suffix != '.md':
            continue
        text = md_file.read_text(encoding='utf-8')
        file_changed = False
        for idx, (old, new) in enumerate(FIXUPS):
            if old in text:
                text = text.replace(old, new)
                hits[idx].append(md_file.name)
                file_changed = True
        if file_changed:
            md_file.write_text(text, encoding='utf-8')
            modified += 1

    # Write report
    _write_report(output_dir, hits)

    return modified


def _write_report(output_dir: Path, hits: dict[int, list[str]]) -> None:
    """Write a fixup report to *output_dir*/index/fixups.md."""
    index_dir = output_dir / 'index'
    index_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append('# Fixup Report')
    lines.append('')
    lines.append('| Fixup | Affected Sections |')
    lines.append('|-------|-------------------|')

    for idx, (old, new) in enumerate(FIXUPS):
        files = hits.get(idx, [])
        label = f'`{old}` → `{new}`'
        if files:
            links = ', '.join(
                f'[{f}](../sections/{f})' for f in sorted(files)
            )
        else:
            links = '*(already applied)*'
        lines.append(f'| {label} | {links} |')

    lines.append('')

    report_path = index_dir / 'fixups.md'
    report_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'  Fixup report: {report_path}')


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == '--from-config':
        cfg = load_config()
        target = sys.argv[2] if len(sys.argv) >= 3 else 'base'
        ver = cfg.base if target == 'base' else cfg.comparison
        count = apply_fixups(ver.output_dir)
        print(f'Fixups applied to {count} file(s) in {ver.output_dir}')
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
