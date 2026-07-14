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

import json
from pathlib import Path
from dataclasses import dataclass

CONFIG_PATH = Path(__file__).resolve().parent / 'config.json'


@dataclass
class VersionConfig:
    version: str
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
    root: Path


def _make_version(data: dict, root: Path) -> VersionConfig:
    od = root / data['output_dir']
    idx = od / 'index'
    return VersionConfig(
        version=data['version'],
        docx=root / data['docx'],
        output_dir=od,
        sections_dir=od / 'sections',
        tables_dir=od / 'tables',
        images_dir=od / 'images',
        index_dir=idx,
        index_file=idx / 'index.json',
    )


def load_config(config_path: Path | str | None = None) -> Config:
    """Load project configuration from scripts/config.json."""
    path = Path(config_path) if config_path else CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(
            f'Config not found: {path}\n'
            f'Run: python -X utf8 scripts/init_config.py'
        )

    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    root = Path(path).resolve().parent.parent
    return Config(
        base=_make_version(data['base'], root),
        comparison=_make_version(data['comparison'], root),
        comparison_dir=root / data['comparison_dir'],
        mapping_file=root / data['mapping_file'],
        root=root,
    )
