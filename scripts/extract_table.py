"""
Extract a single table from an SDCA specification .docx as Markdown.

Usage:
  python extract_table.py <docx_path> <table_number> [--output-dir DIR]

Output: writes Table<num>.md to output-dir, prints "filename|caption" to stdout.

Example:
  python -X utf8 scripts/extract_table.py <docx_path> 3
  → doc/output/tables/Table3.md
  → stdout: Table3.md|Table 3 SDCA Function Type
"""
import sys
import os
import re
import zipfile
from lxml import etree

from common import W, para_to_markdown, table_to_markdown


def extract_table(docx_path, table_num, output_dir='doc/output/tables'):
    """Extract a table by number from a docx. Returns (filename, caption) or (None, None)."""
    os.makedirs(output_dir, exist_ok=True)

    with zipfile.ZipFile(docx_path) as z:
        with z.open('word/document.xml') as f:
            tree = etree.parse(f)

        root = tree.getroot()
        body = root.find(f'{{{W}}}body')

        for p in body:
            if p.tag != f'{{{W}}}p':
                continue
            pPr = p.find(f'{{{W}}}pPr')
            style = ''
            if pPr is not None:
                ps = pPr.find(f'{{{W}}}pStyle')
                if ps is not None:
                    style = ps.get(f'{{{W}}}val')
            if style != 'TableTitle':
                continue

            texts = [t.text or '' for t in p.findall(f'.//{{{W}}}t')]
            text = ''.join(texts).strip()
            m = re.match(rf'Table\s+{table_num}\s+(.+)', text)
            if not m:
                continue

            caption = text
            # Search forward for the next <w:tbl> element.
            # Look up to 20 paragraphs for the associated table
            # (safe upper bound; spec documents keep captions and tables close together).
            next_sib = p.getnext()
            for _ in range(20):
                if next_sib is None:
                    break
                if next_sib.tag == f'{{{W}}}tbl':
                    md = table_to_markdown(next_sib)
                    if md:
                        content = f'**{caption}**\n\n{md}\n'
                        filename = f'Table{table_num}.md'
                        with open(os.path.join(output_dir, filename), 'w', encoding='utf-8') as f:
                            f.write(content)
                        return filename, caption
                    break
                next_sib = next_sib.getnext()

            return None, None

        return None, None


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    docx_path = sys.argv[1]
    table_num = sys.argv[2]
    output_dir = 'doc/output/tables'

    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == '--output-dir' and i + 1 < len(sys.argv):
            output_dir = sys.argv[i + 1]
            i += 2
        else:
            print(f'Unknown arg: {sys.argv[i]}', file=sys.stderr)
            sys.exit(1)

    filename, caption = extract_table(docx_path, table_num, output_dir)
    if filename:
        print(f'{filename}|{caption}')
    else:
        print(f'Table {table_num} not found', file=sys.stderr)
        sys.exit(1)
