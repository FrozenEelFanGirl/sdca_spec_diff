"""
Initialize the SDCA diff project configuration.

Scans doc/sources/ for .docx files, reads metadata (core.xml + cover page),
assigns base (newer) and comparison (older) versions, and generates
scripts/config.json.  All other scripts consume this config.

Usage:
  python -X utf8 scripts/init_config.py                  # auto-detect
  python -X utf8 scripts/init_config.py --clear           # also clear old output
  python -X utf8 scripts/init_config.py --base <path> --comp <path>
"""

import sys
import re
import json
import shutil
import zipfile
from pathlib import Path
from dataclasses import dataclass
from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
DOC_SOURCES = ROOT / 'doc' / 'sources'
CONFIG_PATH = Path(__file__).resolve().parent / 'config.json'

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


# ── Metadata extraction ────────────────────────────────────────────────────

def _read_core_xml(z: zipfile.ZipFile) -> dict:
    """Extract core.xml metadata fields."""
    core = etree.fromstring(z.read('docProps/core.xml'))
    meta = {}
    for child in core:
        tag = child.tag.split('}')[-1]
        if child.text:
            meta[tag] = child.text.strip()
    return meta


def _read_first_page_paragraphs(z: zipfile.ZipFile, limit: int = 40) -> list[str]:
    """Return first non-empty paragraphs from the document (scan all elements for cover page)."""
    doc = etree.fromstring(z.read('word/document.xml'))
    paras = []
    for p in doc.iter(f'{{{W}}}p'):
        text = ''.join(t.text or '' for t in p.iter(f'{{{W}}}t')).strip()
        if text:
            paras.append(text)
            if len(paras) >= limit:
                break
    return paras


def _parse_version_from_cover(paras: list[str]) -> str | None:
    """Parse 'Version X.Y' and optional 'Revision Z' from cover page paragraphs.
    Returns version string like 'v1p2r17' or 'v1p0'."""
    major_minor = None
    revision = 0

    for p in paras:
        if major_minor is None:
            m = re.match(r'^Version\s+(\d+)\.(\d+)', p, re.IGNORECASE)
            if m:
                major_minor = (int(m.group(1)), int(m.group(2)))

        m = re.match(r'^Revision\s+(\d+)', p, re.IGNORECASE)
        if m:
            revision = int(m.group(1))

    if major_minor is None:
        return None

    mm = f'v{major_minor[0]}p{major_minor[1]}'
    if revision > 0:
        return f'{mm}r{revision}'
    return mm


def _parse_date_from_cover(paras: list[str]) -> str | None:
    """Try to find a date on the cover page."""
    for p in paras:
        # e.g. "15 June 2026" or "16 October 2023"
        m = re.search(r'(\d{1,2}\s+(January|February|March|April|May|June|July|'
                       r'August|September|October|November|December)\s+\d{4})', p, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _version_sort_key(version_str: str) -> tuple:
    """Parse 'v1p2r17' → (1, 2, 17) for comparison."""
    m = re.match(r'v(\d+)p(\d+)(?:r(\d+))?', version_str)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
    return (0, 0, 0)


# ── Docx discovery ──────────────────────────────────────────────────────────

@dataclass
class DocInfo:
    path: Path
    filename: str
    version_cover: str | None
    version_core: str | None
    core_title: str | None
    cover_date: str | None
    core_modified: str | None


def inspect_docx(docx_path: Path) -> DocInfo:
    """Extract version metadata from a docx file."""
    z = zipfile.ZipFile(str(docx_path))
    meta = _read_core_xml(z)
    paras = _read_first_page_paragraphs(z)
    z.close()

    version_cover = _parse_version_from_cover(paras)
    cover_date = _parse_date_from_cover(paras)

    # Parse version from core title (e.g. "v1.2 r15" → v1p2r15)
    core_title = meta.get('title', '')
    version_core = None
    m = re.search(r'v(?:ersion\s*)?(\d+)\.(\d+)(?:\s*r(\d+))?', core_title, re.IGNORECASE)
    if m:
        version_core = f'v{m.group(1)}p{m.group(2)}'
        if m.group(3):
            version_core += f'r{m.group(3)}'

    return DocInfo(
        path=docx_path,
        filename=docx_path.name,
        version_cover=version_cover,
        version_core=version_core,
        core_title=core_title,
        cover_date=cover_date,
        core_modified=meta.get('modified', ''),
    )


# ── Config generation ──────────────────────────────────────────────────────

def generate_config(infos: list[DocInfo], clear: bool = False,
                    force_base: Path | None = None, force_comp: Path | None = None):
    """Assign base/comp, validate, write config.json, create directories."""

    # Filter to valid docx files with parsable versions
    valid = [i for i in infos if i.version_cover is not None]
    if len(valid) < 2:
        print('Error: need at least 2 docx files with parsable version info in doc/sources/',
              file=sys.stderr)
        sys.exit(1)

    # Apply overrides or auto-detect
    if force_base and force_comp:
        base_info = next((i for i in valid if i.path == force_base), None)
        comp_info = next((i for i in valid if i.path == force_comp), None)
        if base_info is None:
            print(f'Error: --base file not in valid docx list', file=sys.stderr)
            sys.exit(1)
        if comp_info is None:
            print(f'Error: --comp file not in valid docx list', file=sys.stderr)
            sys.exit(1)
    elif force_base:
        base_info = next((i for i in valid if i.path == force_base), None)
        if base_info is None:
            print(f'Error: --base file not in valid docx list', file=sys.stderr)
            sys.exit(1)
        # Pick the newest remaining as comparison
        remaining = [i for i in valid if i.path != force_base]
        remaining.sort(key=lambda i: _version_sort_key(i.version_cover), reverse=True)
        comp_info = remaining[0]
    elif force_comp:
        comp_info = next((i for i in valid if i.path == force_comp), None)
        if comp_info is None:
            print(f'Error: --comp file not in valid docx list', file=sys.stderr)
            sys.exit(1)
        # Pick the newest remaining as base
        remaining = [i for i in valid if i.path != force_comp]
        remaining.sort(key=lambda i: _version_sort_key(i.version_cover), reverse=True)
        base_info = remaining[0]
    else:
        # Auto-detect: newest is base, second-newest is comparison
        valid.sort(key=lambda i: _version_sort_key(i.version_cover), reverse=True)
        base_info = valid[0]
        comp_info = valid[1]

    base_ver = base_info.version_cover
    comp_ver = comp_info.version_cover

    # ── Warnings ──
    if base_info.version_cover != base_info.version_core:
        print(f'WARNING: {base_info.filename}: cover says "{base_info.version_cover}" '
              f'but core.xml says "{base_info.version_core}" — using cover version.',
              file=sys.stderr)

    if comp_info.version_cover != comp_info.version_core:
        print(f'WARNING: {comp_info.filename}: cover says "{comp_info.version_cover}" '
              f'but core.xml says "{comp_info.version_core}" — using cover version.',
              file=sys.stderr)

    if _version_sort_key(base_ver) <= _version_sort_key(comp_ver):
        print(f'WARNING: base version ({base_ver}) is not newer than comparison ({comp_ver}).',
              file=sys.stderr)

    print(f'Base:       {base_ver}  ({base_info.filename})')
    print(f'Comparison: {comp_ver}  ({comp_info.filename})')
    if base_info.cover_date:
        print(f'Base cover date: {base_info.cover_date}')
    if comp_info.cover_date:
        print(f'Comparison cover date: {comp_info.cover_date}')

    # ── Generate config ──
    comparison_dir = f'doc/comparison_{base_ver}_{comp_ver}'

    config = {
        'base': {
            'version': base_ver,
            'docx': str(base_info.path.relative_to(ROOT).as_posix()),
            'output_dir': f'doc/output_{base_ver}',
        },
        'comparison': {
            'version': comp_ver,
            'docx': str(comp_info.path.relative_to(ROOT).as_posix()),
            'output_dir': f'doc/output_{comp_ver}',
        },
        'comparison_dir': comparison_dir,
        'mapping_file': f'{comparison_dir}/index/full_mapping.json',
    }

    # ── Clear old output if requested ──
    if clear:
        dirs_to_clear = [
            ROOT / config['base']['output_dir'],
            ROOT / config['comparison']['output_dir'],
            ROOT / comparison_dir,
        ]
        for d in dirs_to_clear:
            if d.exists():
                print(f'Clearing: {d.relative_to(ROOT)}')
                shutil.rmtree(str(d))

    # ── Create directory structure ──
    for ver_key in ('base', 'comparison'):
        od = ROOT / config[ver_key]['output_dir']
        for sub in ('sections', 'tables', 'images', 'index'):
            (od / sub).mkdir(parents=True, exist_ok=True)

    cd = ROOT / comparison_dir
    for sub in ('sections', 'tables', 'images', 'index'):
        (cd / sub).mkdir(parents=True, exist_ok=True)

    # ── Write config ──
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f'\nConfig written to {CONFIG_PATH.relative_to(ROOT)}')

    return config


# ── Main ────────────────────────────────────────────────────────────────────

def _check_packages():
    """Verify required packages are installed. Exit with helpful message if not."""
    missing = []
    try:
        from lxml import etree  # noqa: F401
    except ImportError:
        missing.append('lxml')
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append('Pillow')
    if missing:
        print(f'Missing required packages: {", ".join(missing)}', file=sys.stderr)
        print('Install with: pip install ' + ' '.join(missing), file=sys.stderr)
        sys.exit(1)


def main():
    _check_packages()

    force_base = None
    force_comp = None
    clear = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--clear':
            clear = True; i += 1
        elif args[i] == '--base' and i + 1 < len(args):
            p = Path(args[i + 1])
            force_base = p if p.is_absolute() else ROOT / p
            if not force_base.exists():
                print(f'Error: --base file not found: {force_base}', file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == '--comp' and i + 1 < len(args):
            p = Path(args[i + 1])
            force_comp = p if p.is_absolute() else ROOT / p
            if not force_comp.exists():
                print(f'Error: --comp file not found: {force_comp}', file=sys.stderr)
                sys.exit(1)
            i += 2
        else:
            print(f'Unknown argument: {args[i]}', file=sys.stderr)
            sys.exit(1)

    # Discover docx files
    docx_files = sorted(DOC_SOURCES.glob('*.docx'))
    if not docx_files:
        print(f'Error: no .docx files found in {DOC_SOURCES.relative_to(ROOT)}', file=sys.stderr)
        sys.exit(1)

    print(f'Found {len(docx_files)} docx file(s) in doc/sources/')
    infos = [inspect_docx(p) for p in docx_files]
    for info in infos:
        print(f'  {info.filename}: cover={info.version_cover}, core={info.version_core}')

    generate_config(infos, clear=clear, force_base=force_base, force_comp=force_comp)


if __name__ == '__main__':
    main()
