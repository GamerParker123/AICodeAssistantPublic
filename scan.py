import os
import ast
from config import EXCLUDE_DIRS

def scan_files(root_dir):
    files = []
    for dirpath, _, filenames in os.walk(root_dir):
        # Skip common irrelevant folders
        if any(skip in dirpath for skip in EXCLUDE_DIRS):
            continue
        for f in filenames:
            if f.endswith((".py", ".js", ".ts", ".md")):
                files.append(os.path.join(dirpath, f))
    return files

def chunk_file_by_definitions(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        source = f.read()

    tree = ast.parse(source)
    chunks = []
    def_spans = []

    lines = source.splitlines()

    def get_code_snippet(start_lineno, end_lineno):
        return "\n".join(lines[start_lineno - 1 : end_lineno])

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, 'end_lineno', None)
            if end is None:
                end = start + 10
            def_spans.append((start, end))
            code = get_code_snippet(start, end)
            chunks.append({
                "type": "function",
                "name": node.name,
                "start": start,
                "end": end,
                "code": code
            })

    def_spans.sort()
    prev_end = 0
    for start, end in def_spans:
        if prev_end + 1 < start:
            loose_code = get_code_snippet(prev_end + 1, start - 1)
            chunks.append({
                "type": "loose",
                "start": prev_end + 1,
                "end": start - 1,
                "code": loose_code
            })
        prev_end = end

    if prev_end < len(lines):
        loose_code = get_code_snippet(prev_end + 1, len(lines))
        chunks.append({
            "type": "loose",
            "start": prev_end + 1,
            "end": len(lines),
            "code": loose_code
        })

    chunks.sort(key=lambda c: c["start"])
    return chunks
