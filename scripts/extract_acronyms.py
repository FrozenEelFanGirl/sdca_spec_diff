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
Extract acronyms from section 2.4 of an SDCA spec and generate acronyms.json.

Parses the OOXML directly so bold acronym runs are reliably separated from
regular-weight definition runs, avoiding the ambiguity of the markdown output.

Usage:
  python -X utf8 scripts/extract_acronyms.py                  # both versions
  python -X utf8 scripts/extract_acronyms.py --from-config base   # base only

Output per version:
  - Overwrites sections/2.4_Acronyms.md with clean format
  - Writes index/acronyms.json
"""

import sys
import os
import re
import json
import zipfile
from pathlib import Path
from lxml import etree



from config import ROOT  # noqa: E402
from common import W, NS, DEFINITION_STYLES, build_style_map, parse_toc, para_to_markdown, parse_xml


def _para_runs(p_elem):
    """Return the text of each run in a paragraph, in order."""
    texts = []
    for run in p_elem.iter(f'{{{W}}}r'):
        t = run.find(f'{{{W}}}t')
        if t is not None and t.text:
            texts.append(t.text)
    return texts


def _is_acronym_run(text: str) -> bool:
    """A run belongs to the acronym if every character is uppercase, digit,
    slash, or underscore.  Lowercase acronyms are handled by the fallback
    in _split_acronym (first run is used when no run matches)."""
    return bool(re.match(r'^[A-Z0-9/_]+$', text))


def _split_acronym(runs: list[str]) -> tuple[str, str]:
    """Split runs into (acronym, definition)."""
    acr_runs: list[str] = []
    for i, r in enumerate(runs):
        if _is_acronym_run(r):
            # Stop if the next run starts with lowercase — this run is
            # actually the first letter of a definition word (e.g. 'F' in 'Flat').
            if i + 1 < len(runs) and re.match(r'^[a-z]', runs[i + 1]):
                break
            acr_runs.append(r)
        else:
            break

    if not acr_runs and runs:
        # Fallback: no bold/all-caps run found — assume first run is the
        # acronym.  This handles cases like "rms" (root mean square) where
        # the acronym is lowercase and doesn't match _is_acronym_run.
        acr_runs = [runs[0]]

    acronym = ''.join(acr_runs).strip()
    definition = ''.join(runs[len(acr_runs):]).strip()
    return acronym, definition


def extract_acronyms(docx_path: str) -> dict[str, str]:
    """Parse acronyms from section 2.4 of a docx. Returns {ACRONYM: definition}."""
    with zipfile.ZipFile(docx_path) as z:
        doc_xml = z.read('word/document.xml')
        styles_xml = z.read('word/styles.xml')

    root = parse_xml(doc_xml)
    body = root.find(f'{{{W}}}body')

    num_to_heading, heading_to_num = parse_toc(doc_xml)
    style_map = build_style_map(styles_xml)

    # Find the heading element in the body by matching the heading text
    # against the TOC entry (don't rely on the fragile strip-number regex).
    target_normalized = 'acronyms'
    found_section = False
    target_level = None
    acronyms: dict[str, str] = {}

    for child in body:
        if child.tag != f'{{{W}}}p':
            continue

        pPr = child.find('w:pPr', NS)
        style_id = None
        if pPr is not None:
            pStyle = pPr.find('w:pStyle', NS)
            if pStyle is not None:
                style_id = pStyle.get(f'{{{W}}}val')

        lvl = style_map.get(style_id, {}).get('resolved_outline') if style_id else None
        text = para_to_markdown(child).strip()

        if lvl is not None and text:
            if not found_section:
                # Match heading text after stripping section-number prefix
                # (e.g. "2.4 Acronyms" or "A.1 Appendix").  Only strip
                # patterns with digits to avoid eating leading capitals.
                h_norm = re.sub(r'^[\d]+(?:\.[\d]+)*\s*', '', text).strip().lower()
                if h_norm == target_normalized:
                    found_section = True
                    target_level = lvl
                continue
            else:
                if lvl <= target_level:
                    break  # next section — stop

        if not found_section:
            continue

        if style_id in DEFINITION_STYLES:
            runs = _para_runs(child)
            if len(runs) < 2:
                continue

            acronym, definition = _split_acronym(runs)

            if acronym and definition:
                acronyms[acronym] = definition

    return acronyms


def write_output(acronyms: dict[str, str], sections_dir: Path, index_dir: Path):
    """Write cleaned section 2.4 markdown and acronyms.json."""
    # Cleaned markdown
    lines = ['## Acronyms', '']
    for acr in sorted(acronyms.keys(), key=lambda a: a.upper().lstrip('_')):
        defn = acronyms[acr]
        lines.append(f'**{acr}** — {defn}')
        lines.append('')

    section_path = sections_dir / '2.4_Acronyms.md'
    section_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'  Cleaned section: {section_path}')

    # acronyms.json
    os.makedirs(str(index_dir), exist_ok=True)
    acr_path = index_dir / 'acronyms.json'
    with open(acr_path, 'w', encoding='utf-8') as f:
        json.dump(acronyms, f, indent=2, ensure_ascii=False)
    print(f'  Acronyms JSON:   {acr_path}  ({len(acronyms)} entries)')


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == '--from-config':
        from config import load_config
        cfg = load_config()
        target = sys.argv[2] if len(sys.argv) >= 3 else 'base'
        ver = cfg.base if target == 'base' else cfg.comparison
        acronyms = extract_acronyms(str(ver.docx))
        if acronyms:
            write_output(acronyms, ver.sections_dir, ver.index_dir)
    else:
        from config import load_config
        cfg = load_config()
        for label, ver in [('base', cfg.base), ('comparison', cfg.comparison)]:
            print(f'=== Extracting acronyms for {label} ({ver.version}) ===')
            acronyms = extract_acronyms(str(ver.docx))
            if acronyms:
                write_output(acronyms, ver.sections_dir, ver.index_dir)
            else:
                print(f'  No acronyms found for {label}')
            print()


if __name__ == '__main__':
    main()
