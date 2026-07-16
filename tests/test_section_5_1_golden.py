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
Integration test: compare section 5.1 output against the golden file.

Ensures the comparison pipeline produces deterministic, reviewed output
that matches the manually curated golden reference.
"""

import os
import sys
import json
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from config import load_config
from compare_sections import (
    build_comparison,
    read_section_file,
    _strip_blockquotes,
    _split_blocks,
    _split_all,
    _merge_split_numbered_lists,
    _process_blocks,
    _rewrite_assets,
)


class Section51GoldenTest(unittest.TestCase):
    """Verify the comparison output for section 5.1 matches the golden file."""

    @classmethod
    def setUpClass(cls):
        cfg = load_config()
        cls.cfg = cfg
        cls.golden_path = (
            Path(ROOT) / 'tests' /
            '5.1_Overview_of_SDCA_Functions_comparison_golden.md'
        )
        cls.search_report = (
            cfg.comparison_dir / 'index' / 'section_5_1.md'
        )

    def test_golden_file_exists(self):
        self.assertTrue(
            self.golden_path.exists(),
            f'Golden file missing: {self.golden_path}'
        )

    def test_search_report_exists(self):
        self.assertTrue(
            self.search_report.exists(),
            f'Search report missing: {self.search_report}. '
            f'Run: python -X utf8 scripts/search_sections.py --section 5.1'
        )

    def test_section_files_exist(self):
        cfg = self.cfg
        bc = read_section_file(cfg.base.sections_dir, '5.1')
        self.assertIsNotNone(bc, 'Base section 5.1 not found — run extract_all.py')
        cc = read_section_file(cfg.comparison.sections_dir, '5.1')
        self.assertIsNotNone(cc, 'Comparison section 5.1 not found — run extract_all.py')

    def test_output_matches_golden(self):
        """End-to-end: compare section 5.1 and assert output equals golden."""
        cfg = self.cfg

        bc = read_section_file(cfg.base.sections_dir, '5.1')
        cc = read_section_file(cfg.comparison.sections_dir, '5.1')

        # Load mapping to find comp counterpart
        with open(cfg.mapping_file, encoding='utf-8') as f:
            mapping = json.load(f)
        m = None
        for entry in mapping:
            if entry.get('base_num') == '5.1':
                m = entry
                break
        cn = m['comp_num'] if m else '5.1'
        ch = m['comp_heading'] if m else None
        kd = m['kind'] if m else None

        cv = cfg.comparison.version_display
        generated = build_comparison(
            bc, cn, ch, cc, kd, cv,
            base_img_dir=cfg.base.images_dir,
            comp_img_dir=cfg.comparison.images_dir,
        )
        # Asset paths are rewritten with version suffixes in the main()
        # pipeline — the golden file includes these rewritten paths.
        generated = _rewrite_assets(generated, cfg.base.version,
                                   cfg.comparison.version)

        golden = self.golden_path.read_text(encoding='utf-8')

        self.assertEqual(
            golden, generated,
            'Section 5.1 output does not match golden file. '
            'Re-run compare_sections.py and review the diff.'
        )

    def test_block_splitting_deterministic(self):
        """Verify block splitting produces stable output for section 5.1."""
        cfg = self.cfg
        bc = read_section_file(cfg.base.sections_dir, '5.1')
        base_content = _strip_blockquotes(bc)
        base_blocks = _split_blocks(base_content)
        base_blocks = _split_all(base_blocks)
        base_blocks = _merge_split_numbered_lists(base_blocks)

        # Sanity: section 5.1 should have a reasonable number of blocks
        self.assertGreater(len(base_blocks), 5,
                          'Section 5.1 should have more than 5 blocks')
        self.assertLess(len(base_blocks), 200,
                        'Section 5.1 should have fewer than 200 blocks')

    def test_process_blocks_produces_output(self):
        """Verify _process_blocks produces non-empty interleaved output."""
        cfg = self.cfg
        bc = read_section_file(cfg.base.sections_dir, '5.1')
        cc = read_section_file(cfg.comparison.sections_dir, '5.1')

        base_content = _strip_blockquotes(bc)
        comp_content = _strip_blockquotes(cc)
        base_blocks = _split_all(_split_blocks(base_content))
        comp_blocks = _split_all(_split_blocks(comp_content))
        base_blocks = _merge_split_numbered_lists(base_blocks)
        comp_blocks = _merge_split_numbered_lists(comp_blocks)

        result = _process_blocks(base_blocks, comp_blocks,
                                cfg.comparison.version_display,
                                None, None, None)

        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 100,
                          'Interleaved output should be substantial')
        self.assertIn('> **v1.0:**', result,
                      'Output must contain comparison version annotations')


if __name__ == '__main__':
    unittest.main()
