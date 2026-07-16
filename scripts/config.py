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
Shared configuration loader for SDCA diff project.

All scripts import load_config() instead of hardcoding paths.
Before any other script can run, init_config.py must be executed first to
generate scripts/config.json.
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, 'scripts', 'config.json')

REQUIRED_TOP_KEYS = ['base', 'comparison', 'comparison_dir', 'mapping_file']
REQUIRED_VER_KEYS = ['version', 'docx', 'output_dir']


@dataclass
class VersionConfig:
    version: str
    version_display: str     # version with 'p' → '.' (v1p2r17 → v1.2r17)
    docx: Path
    output_dir: Path
    sections_dir: Path
    tables_dir: Path
    images_dir: Path
    index_dir: Path
    index_file: Path


@dataclass
class Config:
    base: VersionConfig
    comparison: VersionConfig
    comparison_dir: Path
    mapping_file: Path
    root: str


def _make_version(data, root):
    od = Path(root) / data['output_dir']
    idx = od / 'index'
    version = data['version']
    return VersionConfig(
        version=version,
        version_display=version.replace('p', '.'),
        docx=Path(root) / data['docx'],
        output_dir=od,
        sections_dir=od / 'sections',
        tables_dir=od / 'tables',
        images_dir=od / 'images',
        index_dir=idx,
        index_file=idx / 'index.json',
    )


def load_config(config_path=None):
    """Load project configuration from scripts/config.json.

    Returns a typed Config with all paths resolved as absolute pathlib.Path
    objects.  Validates required keys and produces a helpful error for
    malformed configs.
    """
    path = config_path if config_path else CONFIG_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(
            'Config not found: %s\n'
            'Run: python -X utf8 scripts/init_config.py' % path
        )

    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    missing_top = [k for k in REQUIRED_TOP_KEYS if k not in data]
    if missing_top:
        raise KeyError(
            'config.json is missing required keys: %s\n'
            'Run init_config.py to regenerate.' % ', '.join(missing_top)
        )

    for label in ('base', 'comparison'):
        missing_ver = [k for k in REQUIRED_VER_KEYS if k not in data.get(label, {})]
        if missing_ver:
            raise KeyError(
                'config.json %s section missing keys: %s\n'
                'Run init_config.py to regenerate.' % (label, ', '.join(missing_ver))
            )

    root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    return Config(
        base=_make_version(data['base'], root),
        comparison=_make_version(data['comparison'], root),
        comparison_dir=Path(root) / data['comparison_dir'],
        mapping_file=Path(root) / data['mapping_file'],
        root=root,
    )
