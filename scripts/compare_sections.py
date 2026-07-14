"""
Generate interleaved comparison files from a search report.

Reads a search report markdown with ✓ checkboxes. For each checked section,
interleaves base content with the comparison counterpart in blockquotes,
aligning paragraphs so the old version text immediately follows each new-version
paragraph.

Usage:
  python -X utf8 scripts/compare_sections.py <report.md>

If <report.md> is not specified, compares ALL sections in the mapping.
"""

import sys
import os
import re
import json
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config


def parse_report(report_path: Path) -> list[str]:
    """Parse a search report markdown, return list of checked section numbers."""
    with open(report_path, encoding='utf-8') as f:
        content = f.read()

    checked = []
    for line in content.split('\n'):
        m = re.match(r'\|\s*✓\s*\|\s*([\d.]+)\s*\|', line)
        if m:
            checked.append(m.group(1))
    return checked


def find_counterpart(section_num: str, mapping: list[dict]) -> dict | None:
    """Find the comparison counterpart for a base section in the mapping."""
    for m in mapping:
        if m.get('base_num') == section_num:
            return m
    return None


def read_section_file(sections_dir: Path, section_num: str) -> str | None:
    """Read a section markdown file by number prefix."""
    prefix = f'{section_num}_'
    for f in sorted(sections_dir.iterdir()):
        if f.name.startswith(prefix) and f.suffix == '.md':
            return f.read_text(encoding='utf-8')
    return None


def _split_blocks(text: str) -> list[str]:
    """Split markdown text into logical blocks for alignment.

    Blocks are separated by blank lines AND by style transitions
    (e.g. a body paragraph followed by a list starts a new block).
    Multi-line elements of the same type stay together.
    """
    raw_blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.split('\n'):
        if not line.strip():
            if current:
                raw_blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        raw_blocks.append(current)

    # Further split blocks at style transitions
    blocks: list[str] = []
    for block_lines in raw_blocks:
        subgroups: list[list[str]] = []
        sub: list[str] = []
        prev_kind: str | None = None
        for line in block_lines:
            stripped = line.strip()
            if re.match(r'^#{1,6}\s', stripped):
                kind = 'heading'
            elif re.match(r'^\s*\d+\.\s', stripped):
                kind = 'numbered'
            elif re.match(r'^\s*[-*]\s', stripped):
                kind = 'bullet'
            elif stripped.startswith('>'):
                kind = 'note'
            elif stripped.startswith('|'):
                kind = 'table'
            elif stripped.startswith('```'):
                kind = 'code'
            elif stripped.startswith('!['):
                kind = 'image'
            else:
                kind = 'body'

            # Notes and body paragraphs don't trigger splits — they stay
            # grouped with adjacent list items (e.g. "> Note:" lines
            # embedded in numbered steps belong to the same block).
            no_split = {'body', 'note'}
            if prev_kind is not None and kind != prev_kind and kind not in no_split:
                if sub:
                    subgroups.append(sub)
                sub = []
            elif prev_kind is not None and prev_kind not in no_split and kind in no_split:
                if sub:
                    subgroups.append(sub)
                sub = []

            sub.append(line)
            prev_kind = kind
        if sub:
            subgroups.append(sub)

        for sg in subgroups:
            blocks.append('\n'.join(sg))

    return blocks


def _is_heading(block: str) -> bool:
    return bool(re.match(r'^#{1,6}\s', block))


def _is_list(block: str) -> bool:
    first = block.split('\n')[0]
    return bool(re.match(r'^\s*[-*\d]+', first))


def _normalize_block(block: str) -> str:
    """Strip formatting for comparison — lowercase, no markdown syntax."""
    t = block.lower()
    t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\*\*([^*]+)\*\*', r'\1', t)
    t = re.sub(r'\*([^*]+)\*', r'\1', t)
    t = re.sub(r'!\[.*?\]\(.*?\)', '', t)
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _block_similarity(b1: str, b2: str) -> float:
    """Similarity between two blocks (0-1) using word trigrams."""
    def trigrams(s):
        words = s.split()
        return set(tuple(words[i:i+3]) for i in range(len(words)-2))
    tg1, tg2 = trigrams(_normalize_block(b1)), trigrams(_normalize_block(b2))
    if not tg1 or not tg2:
        return 0.0
    return len(tg1 & tg2) / len(tg1 | tg2)


def _diff_words(base_text: str, comp_text: str) -> tuple[str, str]:
    """Word-level diff between two texts, preserving line breaks.

    Returns (annotated_base, annotated_comp) where:
      - Words only in base are wrapped in **bold**
      - Words only in comp are wrapped in ~~strikethrough~~
      - Equal words are left unchanged.
    """
    base_lines = base_text.split('\n')
    comp_lines = comp_text.split('\n')

    # If either has multiple lines, diff line-by-line then join
    if len(base_lines) > 1 or len(comp_lines) > 1:
        # Align lines between the two texts
        base_norm = [_normalize_block(l) for l in base_lines]
        comp_norm = [_normalize_block(l) for l in comp_lines]
        sm = SequenceMatcher(None, base_norm, comp_norm)

        base_out: list[str] = []
        comp_out: list[str] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                base_out.extend(base_lines[i1:i2])
                comp_out.extend(comp_lines[j1:j2])
            elif tag == 'replace':
                for k in range(max(i2 - i1, j2 - j1)):
                    bt = base_lines[i1 + k] if k < i2 - i1 else ''
                    ct = comp_lines[j1 + k] if k < j2 - j1 else ''
                    if bt and ct:
                        ab, ac = _diff_words(bt, ct)
                        base_out.append(ab)
                        comp_out.append(ac)
                    elif bt:
                        base_out.append('**' + bt + '**')
                    elif ct:
                        comp_out.append('~~' + ct + '~~')
            elif tag == 'delete':
                for k in range(i1, i2):
                    base_out.append('**' + base_lines[k] + '**')
            elif tag == 'insert':
                for k in range(j1, j2):
                    comp_out.append('~~' + comp_lines[k] + '~~')
        return '\n'.join(base_out), '\n'.join(comp_out)

    # Single-line: word-level diff
    base_words = re.findall(r'\S+', base_text)
    comp_words = re.findall(r'\S+', comp_text)

    sm = SequenceMatcher(None, [w.lower() for w in base_words],
                         [w.lower() for w in comp_words])

    base_parts: list[str] = []
    comp_parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            base_parts.extend(base_words[i1:i2])
            comp_parts.extend(comp_words[j1:j2])
        elif tag == 'replace':
            base_parts.append('**' + ' '.join(base_words[i1:i2]) + '**')
            comp_parts.append('~~' + ' '.join(comp_words[j1:j2]) + '~~')
        elif tag == 'delete':
            base_parts.append('**' + ' '.join(base_words[i1:i2]) + '**')
        elif tag == 'insert':
            comp_parts.append('~~' + ' '.join(comp_words[j1:j2]) + '~~')

    return ' '.join(base_parts), ' '.join(comp_parts)


def _should_inline_diff(block: str) -> bool:
    """Only inline-diff simple body paragraphs, not lists/headings/tables/code."""
    if _is_heading(block) or _is_list(block):
        return False
    if block.startswith('```') or block.startswith('|') or block.startswith('!'):
        return False
    if block.startswith('>') or block.startswith('*'):
        return False
    # Reject blocks that contain list items or note blockquotes on any line
    for line in block.split('\n'):
        stripped = line.strip()
        if re.match(r'^\d+\.\s', stripped):
            return False
        if re.match(r'^\s*[-*]\s', stripped):
            return False
        if stripped.startswith('>'):
            return False
    return True


def _emit_comp_blocks(out: list[str], comp_blocks: list[str],
                      comp_version: str = '') -> None:
    """Append comparison blocks in blockquote format.

    A blank ``>`` line is inserted after the version annotation (and before
    the first list item) so that markdown renderers recognise the list as
    starting a new block.
    """
    if comp_version:
        out.append(f'> **{comp_version}:**')
    if comp_blocks and _is_list(comp_blocks[0]):
        out.append('>')
    for block in comp_blocks:
        for line in block.split('\n'):
            out.append(f'> {line}')
        out.append('>')


def _interleave(base_blocks: list[str], comp_blocks: list[str],
                comp_version: str = '') -> str:
    """Align and interleave base and comparison blocks.

    Uses SequenceMatcher on normalized block text to find matching paragraphs,
    then outputs each base block immediately followed by its comparison
    counterpart (or a 'SAME' annotation for identical blocks).
    """
    if not comp_blocks:
        # No comparison content — just output base blocks
        return '\n\n'.join(base_blocks) + '\n'

    base_norm = [_normalize_block(b) for b in base_blocks]
    comp_norm = [_normalize_block(b) for b in comp_blocks]

    sm = SequenceMatcher(None, base_norm, comp_norm)
    opcodes = sm.get_opcodes()

    out: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'equal':
            # Unchanged blocks — show base, note as unchanged
            for k in range(i1, i2):
                block = base_blocks[k]
                out.append(block)
                if _is_list(block) or _is_heading(block):
                    out.append('')
                else:
                    # Only mark multi-line / non-trivial blocks
                    lines = block.split('\n')
                    if len(lines) == 1:
                        out.append('> *Unchanged.*')
                    else:
                        out.append('> *Unchanged.*')
                    out.append('')

        elif tag == 'replace':
            # Try inline word-level diff for matching pairs within the group.
            # Only applies when both sides are simple paragraphs.
            base_range = list(range(i1, i2))
            comp_range = list(range(j1, j2))
            paired: set[int] = set()  # comp indices already consumed

            for bi in base_range:
                base_block = base_blocks[bi]
                if not _should_inline_diff(base_block):
                    out.append(base_block)
                    out.append('')
                    continue

                # Find best-matching comp block
                best_ci, best_sim = -1, 0.0
                for ci in comp_range:
                    if ci in paired:
                        continue
                    if not _should_inline_diff(comp_blocks[ci]):
                        continue
                    sim = SequenceMatcher(
                        None, _normalize_block(base_block),
                        _normalize_block(comp_blocks[ci])).ratio()
                    if sim > best_sim:
                        best_sim = sim
                        best_ci = ci

                if best_ci >= 0 and best_sim > 0.3:
                    paired.add(best_ci)
                    annotated_base, annotated_comp = _diff_words(
                        base_block, comp_blocks[best_ci])
                    out.append(annotated_base)
                    out.append('')
                    _emit_comp_blocks(out, [annotated_comp], comp_version)
                else:
                    out.append(base_block)
                    out.append('')

            # Remaining unmatched comp blocks
            unmatched = [ci for ci in comp_range if ci not in paired]
            if unmatched:
                unmatched_blocks = [comp_blocks[ci] for ci in unmatched]
                _emit_comp_blocks(out, unmatched_blocks, comp_version)

        elif tag == 'delete':
            # Only in base (new content)
            for k in range(i1, i2):
                out.append(base_blocks[k])
                out.append('')

        elif tag == 'insert':
            # Only in comparison (removed from base)
            insert_blocks = [comp_blocks[k] for k in range(j1, j2)]
            _emit_comp_blocks(out, insert_blocks, comp_version)
            out.append('')

    # Collapse runs of blank lines
    result: list[str] = []
    blank_count = 0
    for line in out:
        if line == '' or line == '>':
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)

    return '\n'.join(result).strip() + '\n'


def build_comparison(base_content: str, comp_num: str | None,
                     comp_heading: str | None, comp_content: str | None,
                     kind: str | None, comp_version: str = '') -> str:
    """Create an interleaved comparison file."""
    lines: list[str] = []

    # Mapping annotation header
    if kind == 'new_section' or comp_num is None:
        lines.append('> **New in this version**')
        lines.append('>')
    elif kind == 'deleted_in_base':
        lines.append(f'> **Removed from this version (was comparison §{comp_num or "?"})**')
        lines.append('>')
    elif comp_num:
        lines.append(f'> **Mapped from comparison §{comp_num}**')
        lines.append('>')

    lines.append('')

    if not comp_content:
        # No comparison counterpart — just output base content
        lines.append(base_content.strip())
        if comp_num:
            lines.append('')
            lines.append(f'> **Comparison §{comp_num}**{f" — {comp_heading}" if comp_heading else ""}')
            lines.append('>')
            lines.append('> *(Comparison section not yet extracted. Run extract_all.py first.)*')
            lines.append('>')
        return '\n'.join(lines) + '\n'

    # Interleave base and comparison blocks
    base_blocks = _split_blocks(base_content)
    comp_blocks = _split_blocks(comp_content)

    interleaved = _interleave(base_blocks, comp_blocks, comp_version)

    lines.append(interleaved)

    # Footer with comparison reference
    lines.append('')
    lines.append(f'> **Comparison §{comp_num}**{f" — {comp_heading}" if comp_heading else ""}')
    lines.append('>')

    return '\n'.join(lines) + '\n'


def main():
    cfg = load_config()

    mapping = []
    if cfg.mapping_file.exists():
        with open(cfg.mapping_file, encoding='utf-8') as f:
            mapping = json.load(f)

    if len(sys.argv) >= 2:
        report_path = Path(sys.argv[1])
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        section_nums = parse_report(report_path)
        print(f'Parsed {len(section_nums)} checked sections from {report_path.name}')
    else:
        section_nums = [m['base_num'] for m in mapping
                        if m.get('base_num') and m.get('kind') != 'deleted_in_base']
        print(f'Comparing all {len(section_nums)} mapped sections')

    if not section_nums:
        print('No sections to compare.')
        return

    comp_sections_dir = cfg.comparison_dir / 'sections'
    os.makedirs(str(comp_sections_dir), exist_ok=True)

    created = 0
    for num in section_nums:
        base_content = read_section_file(cfg.base.sections_dir, num)
        if base_content is None:
            print(f'  SKIP §{num}: not found in base sections')
            continue

        m = find_counterpart(num, mapping)
        comp_num = m['comp_num'] if m else None
        comp_heading = m['comp_heading'] if m else None
        kind = m['kind'] if m else None

        comp_content = None
        if comp_num:
            comp_content = read_section_file(cfg.comparison.sections_dir, comp_num)

        comp_ver_display = cfg.comparison.version.replace('p', '.')
        comparison_text = build_comparison(base_content, comp_num, comp_heading,
                                           comp_content, kind, comp_ver_display)

        base_filename = None
        for f in cfg.base.sections_dir.iterdir():
            if f.name.startswith(f'{num}_') and f.suffix == '.md':
                base_filename = f.name.replace('.md', '_comparison.md')
                break

        if base_filename is None:
            base_filename = f'{num}_comparison.md'

        out_path = comp_sections_dir / base_filename
        out_path.write_text(comparison_text, encoding='utf-8')
        created += 1

    print(f'Created {created} comparison files in {comp_sections_dir.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
