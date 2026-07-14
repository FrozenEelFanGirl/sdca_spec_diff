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
Canonical source for the project MIT license header.

Applies or verifies the copyright header on project source files.
The year is read from the system clock; the author from git config
(or the COPYRIGHT_AUTHOR environment variable).  Language-specific
comment wrappers are derived from a single shared template.

Idempotent — stripping old headers before applying ensures repeated
runs do not produce duplicates.  Uses atomic writes for safety.
"""

import argparse
import difflib
import os
import subprocess
import sys
import tempfile
from datetime import datetime

# ------------------------------------------------------------------
# Shared license template (placeholders: {year}, {author})
# ------------------------------------------------------------------

_LICENSE_TEMPLATE = """\
Copyright (c) {year} {author}

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
THE SOFTWARE."""

C_EXTENSIONS  = {".c", ".h"}
PY_EXTENSIONS = {".py"}
MD_EXTENSIONS = {".md"}

SCAN_LINES = 25
BINARY_CHECK_BYTES = 8192

SKIP_DIRS = {"build", "__pycache__", ".git", ".claude", "official_demo",
             "ref", ".pytest_cache", "node_modules"}

DEFAULT_ROOTS = ["c", "c_fxp", "hifi3z", "python", "scripts"]


# ------------------------------------------------------------------
# Author & year resolution
# ------------------------------------------------------------------

def _get_author(cli_author=None):
    """Return the copyright holder string.

    Precedence: CLI --author > env COPYRIGHT_AUTHOR > git config user.name
    > hardcoded fallback.  If the git name matches the known project author
    handle, appends ' & Senary'.
    """
    if cli_author:
        return cli_author
    env_author = os.environ.get("COPYRIGHT_AUTHOR", "")
    if env_author:
        return env_author
    try:
        result = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True)
        name = result.stdout.strip()
        if name == "FrozenEelFanGirl":
            return "FrozenEelFanGirl & Senary"
        if name:
            return name
    except (OSError, subprocess.SubprocessError):
        pass
    return "FrozenEelFanGirl & Senary"


def _get_year():
    """Return the current year as a string."""
    return str(datetime.now().year)


def _build_license_text(year=None, author=None):
    """Return the formatted license text."""
    return _LICENSE_TEMPLATE.format(
        year=year or _get_year(),
        author=author or _get_author())


# ------------------------------------------------------------------
# Binary detection
# ------------------------------------------------------------------

def _is_binary(filepath):
    """Return True if *filepath* appears to be binary (contains null bytes)."""
    try:
        with open(filepath, "rb") as fh:
            chunk = fh.read(BINARY_CHECK_BYTES)
        return b"\x00" in chunk
    except OSError:
        return True   # unreadable — treat as binary, skip

# ------------------------------------------------------------------
# Language classification
# ------------------------------------------------------------------

def classify_file(filepath):
    """Return 'c', 'python', 'markdown', or 'unknown' for *filepath*."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in C_EXTENSIONS:
        return "c"
    if ext in PY_EXTENSIONS:
        return "python"
    if ext in MD_EXTENSIONS:
        return "markdown"
    return "unknown"

# ------------------------------------------------------------------
# Header builder — wraps license text with language comment syntax
# ------------------------------------------------------------------

def build_header(filepath, year=None, author=None):
    """Return the full copyright header with language-appropriate comments."""
    kind = classify_file(filepath)
    text = _build_license_text(year=year, author=author)
    lines = text.splitlines()

    if kind == "c":
        parts = ["/*"]
        for ln in lines:
            parts.append(" * " + ln if ln else " *")
        parts.append(" */")
        return "\n".join(parts) + "\n\n"

    if kind == "python":
        parts = []
        for ln in lines:
            parts.append("# " + ln if ln else "#")
        return "\n".join(parts) + "\n\n"

    if kind == "markdown":
        parts = ["<!--"]
        for ln in lines:
            parts.append(ln)
        parts.append("-->")
        return "\n".join(parts) + "\n\n"

    return ""

# ------------------------------------------------------------------
# Existing header detection & removal
# ------------------------------------------------------------------

def strip_existing_header(lines, filepath):
    """Remove any existing copyright block.  Returns stripped lines."""
    kind = classify_file(filepath)
    if kind == "unknown":
        return lines

    scan_slice = "".join(lines[:SCAN_LINES]).lower()
    if "copyright" not in scan_slice:
        return lines

    if kind == "c":
        return _strip_c(lines)
    if kind in ("python", "markdown"):
        return _strip_comment_block(lines)

    return lines


def _strip_c(lines):
    """Remove the /* ... */ block containing 'Copyright'.

    Only matches blocks where /* opens the line (after optional whitespace)
    and */ closes it — avoids accidental matches inside string literals
    or mid-line comments.
    """
    copyright_idx = -1
    for i in range(min(SCAN_LINES, len(lines))):
        if "copyright" in lines[i].lower():
            copyright_idx = i
            break
    if copyright_idx < 0:
        return lines

    # Walk backwards to find a line starting (after whitespace) with /*
    block_start = -1
    for i in range(copyright_idx, -1, -1):
        stripped = lines[i].lstrip()
        if stripped.startswith("/*"):
            block_start = i
            break
    if block_start < 0:
        return lines

    # Walk forwards to find a line ending with */
    block_end = -1
    search_end = min(len(lines), block_start + SCAN_LINES * 2)
    for i in range(block_start, search_end):
        if lines[i].rstrip().endswith("*/"):
            block_end = i
            break
    if block_end < 0:
        return lines

    del lines[block_start:block_end + 1]
    _strip_leading_blank(lines)
    return lines


def _strip_comment_block(lines):
    """Remove a contiguous # / <!-- --> comment block containing 'Copyright'.

    Works for Python (# ...) and Markdown (<!-- ... -->) headers.
    """
    copyright_idx = -1
    for i in range(min(SCAN_LINES, len(lines))):
        if "copyright" in lines[i].lower():
            copyright_idx = i
            break
    if copyright_idx < 0:
        return lines

    # Walk backwards to find block start
    block_start = copyright_idx
    for i in range(copyright_idx - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("#") or stripped.startswith("<!--"):
            block_start = i
        elif stripped == "":
            block_start = i
        else:
            break

    # Adjust forward past blank-only lines
    while (block_start < len(lines)
           and lines[block_start].strip() == ""
           and block_start < copyright_idx):
        block_start += 1

    # Walk forwards to find block end
    block_end = copyright_idx
    for i in range(copyright_idx + 1, min(len(lines),
                                           copyright_idx + SCAN_LINES)):
        stripped = lines[i].strip()
        if stripped == "":
            block_end = i
        elif stripped.startswith("#") or stripped.startswith("-->"):
            block_end = i
        else:
            break

    del lines[block_start:block_end + 1]
    _strip_leading_blank(lines)
    return lines


def _strip_leading_blank(lines):
    """Remove leading blank lines from *lines* in-place."""
    while lines and lines[0].strip() == "":
        lines.pop(0)

# ------------------------------------------------------------------
# Exact-match check
# ------------------------------------------------------------------

def has_exact_header(filepath, year=None, author=None):
    """Return True if *filepath* already starts with the correct header."""
    expected = build_header(filepath, year=year, author=author)
    if not expected:
        return True
    if _is_binary(filepath):
        return True
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read(len(expected) + 512)  # +512 for shebang slack
    except (OSError, UnicodeDecodeError):
        return True

    offset = 0
    if content.startswith("#!"):
        nl = content.find("\n")
        if nl >= 0:
            offset = nl + 1
            if offset < len(content) and content[offset] == "\n":
                offset += 1

    actual = content[offset:offset + len(expected)]
    return actual == expected

# ------------------------------------------------------------------
# Apply
# ------------------------------------------------------------------

def apply_header(filepath, dry_run=False, year=None, author=None):
    """Ensure *filepath* has the correct copyright header.

    Returns one of: 'skip', 'updated', 'would_update', 'binary',
    'permission_denied'.
    """
    kind = classify_file(filepath)
    if kind == "unknown":
        return "skip"

    if _is_binary(filepath):
        return "binary"

    expected = build_header(filepath, year=year, author=author)
    actual_start = ""
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            actual_start = fh.read(len(expected) + 512)
    except PermissionError:
        return "permission_denied"
    except (OSError, UnicodeDecodeError):
        return "skip"

    # Check shebang-aware
    offset = 0
    if actual_start.startswith("#!"):
        nl = actual_start.find("\n")
        if nl >= 0:
            offset = nl + 1
            if offset < len(actual_start) and actual_start[offset] == "\n":
                offset += 1

    if actual_start[offset:offset + len(expected)] == expected:
        return "skip"

    if dry_run:
        return "would_update"

    # Read full content
    try:
        with open(filepath, "r", encoding="utf-8", newline="") as fh:
            content = fh.read()
    except PermissionError:
        return "permission_denied"

    lines = content.splitlines(keepends=False)
    _strip_leading_blank(lines)

    shebang = ""
    if lines and lines[0].startswith("#!"):
        shebang = lines.pop(0) + "\n"
        _strip_leading_blank(lines)

    lines = strip_existing_header(lines, filepath)

    new_header = build_header(filepath, year=year, author=author)

    if shebang:
        new_content = shebang + "\n" + new_header + "\n".join(lines)
    else:
        new_content = new_header + "\n".join(lines)

    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    # Atomic write: temp file + rename
    tmp = filepath + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_content)
        os.replace(tmp, filepath)
    except PermissionError:
        _cleanup_tmp(tmp)
        return "permission_denied"
    except OSError:
        _cleanup_tmp(tmp)
        raise

    return "updated"


def _cleanup_tmp(path):
    """Remove a stale temp file if it exists."""
    try:
        os.remove(path)
    except OSError:
        pass

# ------------------------------------------------------------------
# Diff mode
# ------------------------------------------------------------------

def show_diff(filepath, year=None, author=None):
    """Print a unified diff of what would change for *filepath*."""
    expected = build_header(filepath, year=year, author=author)
    if not expected or _is_binary(filepath):
        return

    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            original = fh.read()
    except OSError:
        print(f"  ERROR reading: {filepath}")
        return

    # Build new content the same way apply_header does
    lines = original.splitlines(keepends=False)
    _strip_leading_blank(lines)

    shebang = ""
    if lines and lines[0].startswith("#!"):
        shebang = lines.pop(0) + "\n"
        _strip_leading_blank(lines)

    lines = strip_existing_header(lines, filepath)

    if shebang:
        new_content = shebang + "\n" + expected + "\n".join(lines)
    else:
        new_content = expected + "\n".join(lines)

    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    if original == new_content:
        return   # no diff

    original_lines = original.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines, new_lines,
        fromfile=f"a/{filepath}", tofile=f"b/{filepath}")
    sys.stdout.writelines(diff)

# ------------------------------------------------------------------
# File discovery
# ------------------------------------------------------------------

def find_files(paths, include_md=False):
    """Return a sorted list of source file paths under *paths*."""
    extensions = C_EXTENSIONS | PY_EXTENSIONS
    if include_md:
        extensions |= MD_EXTENSIONS

    result = []
    for raw in paths:
        if os.path.isfile(raw):
            ext = os.path.splitext(raw)[1].lower()
            if ext in extensions:
                result.append(os.path.normpath(raw))
        elif os.path.isdir(raw):
            for root, dirs, files in os.walk(raw):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                           and not d.startswith(".")]
                for fn in files:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in extensions:
                        result.append(os.path.normpath(os.path.join(root, fn)))
    return sorted(result)

# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Apply/verify the MIT copyright header on project source "
                    "files.  Year is read from the system clock; author from "
                    "git config, $COPYRIGHT_AUTHOR, or --author.")
    parser.add_argument(
        "paths", nargs="*",
        help="files or directories to process (default: project source roots)")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-n", "--dry-run", action="store_true",
        help="print what would change without writing")
    mode.add_argument(
        "-c", "--check", action="store_true",
        help="exit 1 if any file lacks the correct header")
    mode.add_argument(
        "--diff", action="store_true",
        help="show unified diff of what would change for each file")

    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="print per-file status")
    parser.add_argument(
        "--include-md", action="store_true",
        help="include .md files (skipped by default)")
    parser.add_argument(
        "--author", default=None,
        help="copyright holder name (default: from git config or env)")
    parser.add_argument(
        "--year", default=None,
        help="copyright year (default: current year from system clock)")
    args = parser.parse_args()

    year = args.year or _get_year()
    author = _get_author(args.author)

    paths = args.paths if args.paths else DEFAULT_ROOTS
    files = find_files(paths, args.include_md)

    if not files:
        print("No source files found.")
        return 0

    # Clean up stale .tmp files from interrupted previous runs
    for fp in files:
        tmp = fp + ".tmp"
        if os.path.isfile(tmp):
            _cleanup_tmp(tmp)

    if args.diff:
        for fp in files:
            show_diff(fp, year=year, author=author)
        return 0

    updated = 0
    skipped = 0
    bad = 0

    for fp in files:
        if args.check:
            if not has_exact_header(fp, year=year, author=author):
                print(f"MISSING/WRONG HEADER: {fp}")
                bad += 1
        else:
            status = apply_header(fp, dry_run=args.dry_run,
                                  year=year, author=author)
            if status == "skip":
                skipped += 1
                if args.verbose:
                    print(f"  SKIP: {fp}")
            elif status == "binary":
                skipped += 1
            elif status == "permission_denied":
                print(f"  PERMISSION DENIED: {fp}")
                bad += 1
            elif status in ("updated", "would_update"):
                updated += 1
                label = "WOULD UPDATE" if args.dry_run else "OK"
                print(f"  {label}: {fp}")

    if args.dry_run:
        print(f"\nWould update {updated}, skip {skipped} ({len(files)} total)")
    elif args.check:
        if bad:
            print(f"\n{bad} file(s) missing or have wrong header "
                  f"(out of {len(files)} checked)")
            return 1
        print(f"\nAll {len(files)} files have correct headers.")
    else:
        print(f"\nUpdated {updated}, skipped {skipped} ({len(files)} total)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
