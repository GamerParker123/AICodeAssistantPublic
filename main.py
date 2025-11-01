from openai import OpenAI
from embedding_utils import build_index
from gui import AIEditorGUI
import os
import shutil
import time
import sys
import tkinter as tk

# NOTE: All suggestions in this code were written by the coding assistant itself
# So it's iterating on its own code
# Pretty neat!
# - Konner



# Note: instantiating an OpenAI client at import time can make testing harder
# and will raise if required credentials aren't provided. Consider:
# - Creating the client inside main() or a factory function so you can pass
#   an explicit API key (from env/config) and make it easier to mock in tests.
# - Using OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") and passing it to OpenAI(api_key=...)
# - Failing fast with a clear error message if no API key is present.
client = OpenAI()

INDEX_TIMESTAMP_FILE = ".index_timestamp"
EXCLUDE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__"}

# Suggestion: consider allowing the root directory to be passed as an argument
# so this function can be reused for other paths or tests.
# Also consider using pathlib.Path for clearer path handling across platforms.
def get_latest_source_mtime(root="."):
    """
    Walk the repository tree (excluding EXCLUDE_DIRS) and return the most recent
    modification time among all files. Returns 0.0 if no files are readable.
    """
    latest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        # prune excluded directories to avoid scanning deps/build artifacts
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fname in filenames:
            # skip the timestamp file itself
            if fname == INDEX_TIMESTAMP_FILE or os.path.join(dirpath, fname) == INDEX_TIMESTAMP_FILE:
                continue
            path = os.path.join(dirpath, fname)
            try:
                m = os.path.getmtime(path)
                if m > latest:
                    latest = m
            except Exception:
                # ignore files we can't stat (permissions, broken symlinks, etc.)
                continue
    return latest
# Suggestion: use more specific exceptions for robustness (e.g., FileNotFoundError, ValueError).
# For long-running operations (index/build), catch and log expected errors separately
# and avoid broad except: clauses -- they hide bugs. Use logging.getLogger(...) instead of prints.
def read_index_timestamp():
    """
    Read the stored index timestamp from INDEX_TIMESTAMP_FILE.
    Returns 0.0 if the file does not exist or cannot be parsed.
    """
    try:
        with open(INDEX_TIMESTAMP_FILE, "r", encoding="utf-8") as f:
            ts = float(f.read().strip())
            return ts
    except Exception:
        return 0.0

def write_index_timestamp(ts=None):
    """
    Write a timestamp to INDEX_TIMESTAMP_FILE. If ts is None, use current time.
    This is used to avoid rebuilding the index unnecessarily.
    """
    try:
        if ts is None:
            ts = time.time()
        # Ensure directory exists for the timestamp file
        dirpath = os.path.dirname(INDEX_TIMESTAMP_FILE)
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath, exist_ok=True)
        with open(INDEX_TIMESTAMP_FILE, "w", encoding="utf-8") as f:
            f.write(str(ts))
    except Exception as e:
        # Suggestion: consider logging to a logger rather than printing, for better control.
        print(f"Warning: could not write index timestamp file: {e}")
root_dir = sys.argv[1] if len(sys.argv) > 1 else "."
print(f"Using root directory: {root_dir}")
# Store the index timestamp file inside the chosen root directory so the timestamp corresponds to that tree.
INDEX_TIMESTAMP_FILE = os.path.join(root_dir, ".index_timestamp")

# Initial index status check to avoid expensive rebuilds when not necessary.
print("Checking index status...")
latest_source_mtime = get_latest_source_mtime(root_dir)
index_timestamp = read_index_timestamp()

if index_timestamp >= latest_source_mtime and index_timestamp > 0:
    print("Index is up-to-date. Skipping rebuild.")
else:
    print("Building/rebuilding index...")
    # NOTE: build_index can be expensive. We only rebuild when source files changed since last build.
    # Suggestion: consider running build_index in a background thread/process if startup latency matters.
    # Also check build_index signature — other parts of the code call build_index(new_dir),
    # so passing root_dir here is likely more correct and avoids global state reliance.
    build_index()
    write_index_timestamp()
def main():
    # Consider initializing resources (API client, embedding index, etc.) here and
    # passing them into AIEditorGUI so dependencies are explicit and easier to test.
    # Wrapping the GUI startup in try/except can produce a friendlier error message.
    root = tk.Tk()
    app = AIEditorGUI(root)
    root.mainloop()
if __name__ == "__main__":
    # On Windows, if using multiprocessing/threads for background indexing, consider:
    # from multiprocessing import freeze_support; freeze_support()
    # Also consider parsing CLI args with argparse and returning proper exit codes.
    main()