import difflib
import re
from collections import defaultdict
from logic import normalize_path
import os

def preview_diff(old, new):
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        lineterm="", fromfile="old", tofile="new"
    )
    return "\n".join(diff)

def apply_change(path, new_content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)

def parse_updated_chunks(text):
    print("RAW AI OUTPUT:\n", text)
    pattern = re.compile(
        r"--- FILE: (.*?) ---\n--- CHUNK START: lines (\d+)-(\d+) ---\n(.*?)\n--- CHUNK END ---",
        re.DOTALL
    )
    chunks = []
    for match in pattern.finditer(text):
        file_path = match.group(1)
        start_line = int(match.group(2))
        end_line = int(match.group(3))
        code = match.group(4).rstrip()
        chunks.append({
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "code": code
        })
    return chunks

def apply_updated_chunks_to_file(orig_code, chunks):
    """
    Apply multiple chunks to a single file.
    Chunks must have 'start_line', 'end_line', 'code', 'file_path'.
    """
    lines = orig_code.splitlines()
    for chunk in sorted(chunks, key=lambda c: c['start_line']):
        start = max(0, chunk['start_line'] - 1)
        end = min(len(lines), chunk['end_line'])
        new_lines = chunk['code'].splitlines()
        if not new_lines:
            continue
        print(f"Applying chunk to lines {start+1}-{end} of {normalize_path(chunk['file_path'])}")
        lines[start:end] = new_lines
    return "\n".join(lines)

def apply_chunks_cross_file(updated_chunks):
    """
    Returns a dict: normalized file path -> merged code.
    """
    file_map = defaultdict(list)
    for chunk in updated_chunks:
        file_map[normalize_path(chunk["file_path"])].append(chunk)

    merged_files = {}
    for path, chunks in file_map.items():
        if not os.path.exists(path):
            print(f"Warning: file does not exist: {path}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            orig_code = f.read()
        merged_code = apply_updated_chunks_to_file(orig_code, chunks)
        merged_files[path] = merged_code
    return merged_files
