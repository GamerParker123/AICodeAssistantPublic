import os
import chromadb
import ast
from openai import OpenAI
from scan import scan_files, chunk_file_by_definitions
from config import CHROMA_DB_PATH, OPENAI_API_KEY, EXCLUDE_DIRS, PROJECT_PATH
import json

CACHE_FILE = "file_summaries_cache.json"

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

client = OpenAI(api_key=OPENAI_API_KEY)

def extract_file_metadata(file_path, cache):
    current_mtime = os.path.getmtime(file_path)

    # Check cache first
    if file_path in cache:
        cached = cache[file_path]
        cached_mtime = cached.get("mtime")
        if cached_mtime == current_mtime:
            # Cache is valid
            return {
                "path": file_path,
                "summary": cached["summary"],
                "symbols": cached["symbols"],
                "code": None  # optionally don't load full code here
            }

    # Cache is missing or stale, generate metadata and summary
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except Exception as e:
        print(f"Failed to parse {file_path}: {e}")
        return None

    symbols = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.append(target.id)
                elif isinstance(target, ast.Tuple):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            symbols.append(elt.id)

    summary = ast.get_docstring(tree)

    if not summary:
        prompt = (
            "Summarize this Python file in one short sentence, focusing on its purpose, "
            "not on how it works. Avoid generic phrases.\n\n"
            f"Symbols: {', '.join(symbols)}\n\n"
            "Code:\n"
            f"{source}"
        )
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-nano",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that writes concise file summaries."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=50
            )
            summary = response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Failed to generate AI summary for {file_path}: {e}")
            summary = f"Defines {len(symbols)} symbols: {', '.join(symbols[:5])}" + (", ..." if len(symbols) > 5 else "")

    # Update cache with new summary and current mtime
    cache[file_path] = {
        "summary": summary,
        "symbols": symbols,
        "mtime": current_mtime
    }

    return {
        "path": file_path,
        "summary": summary,
        "symbols": symbols,
        "code": source
    }

def load_all_file_metadata(root_dir=None):
    if root_dir is None:
        root_dir = os.getcwd()  # fallback if nothing is passed
    
    cache = load_cache()
    all_paths = scan_files(root_dir)
    all_metas = []
    for path in all_paths:
        meta = extract_file_metadata(path, cache)
        if meta:
            all_metas.append(meta)
    save_cache(cache)
    return all_metas

def build_index(project_path=None):
    if project_path is None:
        project_path = PROJECT_PATH
    chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    try:
        chroma_client.delete_collection(name="codebase")
        collection = chroma_client.create_collection(name="codebase")
        print("Using existing collection.")
        all_data = collection.get()
        all_ids = all_data.get("ids", [])
        if all_ids:
            collection.delete(ids=all_ids)
    except chromadb.errors.NotFoundError:
        collection = chroma_client.create_collection(name="codebase")
        print("Created new collection.")

    cache = load_cache()
    files = scan_files(project_path)
    print(f"Found {len(files)} files to index.")

    for path in files:
        meta = extract_file_metadata(path, cache)
        if not meta:
            continue

        # Use new chunking by definitions
        chunks = chunk_file_by_definitions(path)

        for i, chunk_data in enumerate(chunks):
            chunk_code = chunk_data["code"]
            embedding = client.embeddings.create(
                model="text-embedding-3-small",
                input=chunk_code
            ).data[0].embedding

            # Build metadata for chunk
            chunk_meta = {
                "path": path,
                "chunk": i,
                "summary": meta["summary"],
                "symbols": ", ".join(meta["symbols"]),
                "chunk_type": chunk_data["type"],
                "chunk_name": chunk_data.get("name", ""),
                "start_line": chunk_data["start"],
                "end_line": chunk_data["end"],
            }

            collection.add(
                documents=[chunk_code or "NO_CODE_FOUND"],
                metadatas=[chunk_meta],
                ids=[f"{path}-{i}"],
                embeddings=[embedding]
            )
            print(f"Indexed chunk {i} from {path}: {chunk_code[:60]}...")

    save_cache(cache)
    print("Index build complete.")
