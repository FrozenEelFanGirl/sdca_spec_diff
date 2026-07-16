<!--
Copyright (c) 2026 FrozenEelFanGirl & Senary

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
-->

# SDCA SpecDiff

Compare two versions of the MIPI SDCA specification and produce annotated interleaved diffs showing exactly what changed between revisions.

## Prerequisites

Python 3.14 and the packages listed in `requirements.txt`.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate                    # Windows (Git Bash)
# .venv\Scripts\activate.bat                     # Windows (CMD)
# .venv\Scripts\Activate.ps1                     # Windows (PowerShell)
# source .venv/bin/activate                      # macOS / Linux
pip install -r requirements.txt
# pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/  # Alibaba Cloud mirror
```

If the download is slow or fails, switch to the Alibaba Cloud mirror by uncommenting
the last line and commenting out the line above it.

## Source Documents

Place `.docx` specification files in `doc/sources/`:

```
doc/sources/
  mipi_DRAFT_SDCA_specification_v1-2r17.docx   # newer (base)
  mipi_DRAFT_SDCA_specification_v1-1r25.docx   # intermediate (ignored)
  mipi_SDCA_specification_v1-0.docx             # oldest (comparison)
```

The project auto-detects the newest version as base and the oldest as comparison by reading the cover page of each document. Intermediate versions are ignored.

## Workflow

### Stage 1 — Preparation (one-time)

**1. Initialize the project:**

```bash
python -X utf8 scripts/init_config.py --clear
```

This scans `doc/sources/`, reads version metadata from each `.docx`, assigns base and comparison roles, and generates the project configuration. The `--clear` flag removes any previous extraction output.

**2. Extract everything:**

```bash
python -X utf8 scripts/extract_all.py          # clears old output by default
python -X utf8 scripts/extract_all.py --no-clean  # keep existing output
```

This runs the full pipeline: builds master indexes → extracts all sections/tables/figures → applies text fixups → parses acronyms from section 2.4 → maps sections between versions → fingerprints content similarity. All output goes under `doc/output_<base>/`, `doc/output_<comp>/`, and `doc/comparison_<base>_<comp>/`.

### Stage 2 — Compare a Topic (repeat for each area of interest)

**1. Search for sections:**

```bash
# Word-level AND matching (acronym expansion, prefix support):
python -X utf8 scripts/search_sections.py "software sequence"
# Exact phrase matching (words must appear consecutively):
python -X utf8 scripts/search_sections.py --phrase "DisCo Addressing"
# Pre-select a specific section number:
python -X utf8 scripts/search_sections.py --section 5.1
```

Produces a checklist of **all** 592 sections, with matching ones pre-checked (`✓`). Reports are saved to `doc/comparison_<base>_<comp>/index/<keyword>.md` (or `section_<num>.md` for `--section`).

**2. Select sections to compare:**

Edit the generated report — remove `✓` from unwanted rows, or add `✓` to additional sections.

**3. Generate comparison files:**

```bash
python -X utf8 scripts/compare_sections.py doc/comparison_<base>_<comp>/index/<keyword>.md
```

This creates interleaved comparison files for each checked section. Paragraphs are aligned by content similarity: each base paragraph is immediately followed by its comparison counterpart in blockquotes (prefixed with `> **vX.Y:**`). Body paragraphs get word-level inline diffs — **bold** for new/changed text, ~~strikethrough~~ for removed text. Lists, tables, and code blocks are shown as-is.

**4. Annotate changes:**

Edit each `_comparison.md` file to mark what changed — bold for new/changed text, strikethrough for removed text.

## Directory Structure

```
doc/
  sources/                    # <-- place .docx files here
  output_<base>/              # extracted base version
    index/index.json          # tracked in git
    index/acronyms.json       # tracked in git (from section 2.4)
    sections/                 # section markdown
    tables/                   # standalone table files
    images/                   # extracted figures (PNG)
  output_<comp>/              # extracted comparison version
    index/index.json          # tracked in git
    ...
  comparison_<base>_<comp>/   # diff output
    index/                    # full_mapping.json + search reports + fingerprints
    sections/                 # interleaved comparison files
    images/                   # version-suffixed figure copies
    tables/                   # version-suffixed table copies
scripts/
  common.py                   # shared OOXML utilities, markdown rendering, logging
  config.py                   # typed config loader + ROOT export + validation
  init_config.py              # discover versions, generate config (auto: newest vs oldest)
  extract_all.py              # full extraction pipeline
  extract_index.py            # build master index
  extract_section.py          # extract single section or all sections (--all)
  extract_acronyms.py         # parse acronyms from section 2.4
  extract_fixups.py           # text corrections (basic + version-specific)
  extract_figure.py           # extract single figure
  extract_table.py            # extract single table
  map_sections.py             # map + fingerprint sections across versions
  search_sections.py          # full-text keyword search (with acronym expansion)
  compare_sections.py         # generate interleaved comparison files (word-level diff)
  diff_images.py              # pixel-diff two figures
tests/
  test_section_5_1_golden.py  # integration test against golden comparison
  5.1_*_comparison_golden.md  # manually reviewed reference output
```

## Notes

- The `-X utf8` flag is required on Windows; the specification contains non-ASCII characters (®, ™, etc.).
- All scripts use the configuration generated by `init_config.py`. Running any script before `init_config.py` will produce an error telling you to run it first.
- The `doc/` directory contents are git-ignored since they include large source documents and generated output.
- `extract_all.py` clears old output by default. Use `--no-clean` to keep existing extractions.
- Run tests with: `python -X utf8 -m unittest tests.test_section_5_1_golden -v`
