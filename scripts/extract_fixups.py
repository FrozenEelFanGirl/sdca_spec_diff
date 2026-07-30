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
import os
from pathlib import Path



from config import load_config, ROOT  # noqa: E402

# ── Fixup tables ─────────────────────────────────────────────────────────────
# Each entry is (exact_old_string, replacement_string).
# Only whole-text matches are replaced — no regex, no partial-word matching.
#
# Two tiers:
#   BASIC_FIXUPS   — applied to every version (encoding glitches, common typos)
#   VERSION_FIXUPS — keyed by version string (v1p0, v1p2r17, …); only applied
#                     to the matching version's output

BASIC_FIXUPS: list[tuple[str, str]] = [
    # Non-breaking space → regular space in cross-reference prefixes
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
]

VERSION_FIXUPS: dict[str, list[tuple[str, str]]] = {
    'v1p2r17': [
        # em-dash → hyphen in specific property name (base version only)
        (
            'mipi-sdca-function-topology—pipe',
            'mipi-sdca-function-topology-pipe',
        ),
        # en-dash → hyphen in number range
        (
            '56–63',
            '56-63',
        ),
        # Typo in source document
        (
            'inisde',
            'inside',
        ),
    ],
}


def apply_fixups(output_dir: Path, version: str = '') -> int:
    """Apply BASIC_FIXUPS + version-specific VERSION_FIXUPS[version] to every
    .md file in *output_dir*/sections/.

    Returns the number of files modified.
    """
    sections_dir = output_dir / 'sections'
    if not sections_dir.is_dir():
        print(f'  Sections dir not found: {sections_dir}', file=sys.stderr)
        return 0

    all_fixups = list(BASIC_FIXUPS)
    if version and version in VERSION_FIXUPS:
        all_fixups.extend(VERSION_FIXUPS[version])

    modified = 0
    hits: dict[int, list[str]] = {i: [] for i in range(len(all_fixups))}

    for md_file in sorted(sections_dir.iterdir()):
        if md_file.suffix != '.md':
            continue
        text = md_file.read_text(encoding='utf-8')
        file_changed = False
        for idx, (old, new) in enumerate(all_fixups):
            if old in text:
                text = text.replace(old, new)
                hits[idx].append(md_file.name)
                file_changed = True
        if file_changed:
            md_file.write_text(text, encoding='utf-8')
            modified += 1

    _write_report(output_dir, hits, all_fixups)

    return modified


def _write_report(output_dir: Path, hits: dict[int, list[str]],
                  fixups: list[tuple[str, str]]) -> None:
    """Write a fixup report to *output_dir*/index/fixups.md."""
    index_dir = output_dir / 'index'
    index_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append('# Fixup Report')
    lines.append('')
    lines.append('| Fixup | Affected Sections |')
    lines.append('|-------|-------------------|')

    for idx, (old, new) in enumerate(fixups):
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
        count = apply_fixups(ver.output_dir, ver.version)
        print(f'Fixups applied to {count} file(s) in {ver.output_dir}')
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
