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
Golden check for section 4.7.2 (paragraph word diff).

Prerequisite:
  python -X utf8 scripts/extract_all.py
  python -X utf8 scripts/map_sections.py
  python -X utf8 scripts/map_fixups.py
  python -X utf8 scripts/search_sections.py --section 4.7.2
  python -X utf8 scripts/compare_sections.py doc/comparison_<base>_<comp>/index/section_4_7_2.md

This test asserts the generated comparison file is byte-for-byte identical
to the manually reviewed golden file.

Limitation: Windows-only — the byte comparison includes line endings (both
files are CRLF); on macOS/Linux the workflow writes LF and the check fails.
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from config import load_config


class Section472GoldenTest(unittest.TestCase):
    """Compare the workflow-generated 4.7.2 comparison file with the golden file."""

    @classmethod
    def setUpClass(cls):
        cfg = load_config()
        cls.golden = (
            Path(ROOT) / 'tests' /
            '4.7.2_Soft_Warm_Reset_comparison_golden.md'
        )
        cls.output = (
            cfg.comparison_dir / 'sections' /
            cls.golden.name.replace('_comparison_golden.md', '_comparison.md')
        )

    def test_comparison_matches_golden(self):
        self.assertTrue(
            self.golden.exists(),
            f'Golden file missing: {self.golden}'
        )
        self.assertTrue(
            self.output.exists(),
            f'Comparison file missing: {self.output}\n'
            'Complete the section 4.7.2 workflow first:\n'
            '  python -X utf8 scripts/search_sections.py --section 4.7.2\n'
            '  python -X utf8 scripts/compare_sections.py '
            'doc/comparison_<base>_<comp>/index/section_4_7_2.md'
        )
        self.assertEqual(
            self.golden.read_bytes(), self.output.read_bytes(),
            'Comparison file is not byte-identical to the golden file '
            '(content, line endings, or encoding). Inspect with:\n'
            f'  diff "{self.output}" "{self.golden}"'
        )


if __name__ == '__main__':
    unittest.main()
