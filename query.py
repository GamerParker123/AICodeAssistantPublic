import chromadb
from openai import OpenAI
from config import OPENAI_API_KEY, CHROMA_DB_PATH
from embedding_utils import build_index
import json
from collections import defaultdict

client = OpenAI(api_key=OPENAI_API_KEY)
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

try:
    collection = chroma_client.get_collection(name="codebase")
except chromadb.errors.NotFoundError:
    raise RuntimeError("No collection found. Run build_index() first.")

def search_context(query, top_k=5):
    query_embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    ).data[0].embedding

    results = collection.query(query_embeddings=[query_embedding], n_results=top_k)
    print("Search results documents:", results["documents"])
    print("Search results metadatas:", results["metadatas"])
    # results["documents"] is a list of lists (one per query), so flatten it.
    docs = [doc for sublist in results["documents"] for doc in sublist]
    metas = [meta for sublist in results["metadatas"] for meta in sublist]
    # Consider returning distances too if available, e.g.:
    # distances = [dist for sublist in results.get("distances", []) for dist in sublist]
    return docs, metas

def choose_chunks_by_instruction(instruction, max_chunks=5):
    # Get embedding for instruction
    instruction_embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=instruction
    ).data[0].embedding

    chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = chroma_client.get_collection(name="codebase")

    results = collection.query(
        query_embeddings=[instruction_embedding],
        n_results=max_chunks,
        include=['documents', 'metadatas']
    )

    chunks = []
    for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
        chunks.append({
            "code": doc,
            "metadata": meta
        })

    return chunks

def group_chunks_by_file(chunks):
    files = defaultdict(list)
    for chunk in chunks:
        path = chunk['metadata']['path']
        files[path].append(chunk)
    return files

def prepare_prompt_with_chunks(user_request, metas, collection, chunk_ids, current_file_path):
    chunked_docs = []
    for chunk_id in chunk_ids:
        results = collection.get(ids=[str(chunk_id)])
        if not results or not results['documents']:
            continue

        code_chunk = results['documents'][0]
        if not code_chunk or (isinstance(code_chunk, list) and not code_chunk[0]):
            print(f"Empty chunk for ID {chunk_id}")
            code_chunk = "<EMPTY>"
        if isinstance(code_chunk, list):
            code_chunk = code_chunk[0] if code_chunk else ""

        meta = results['metadatas'][0]

        chunked_docs.append({
            "code": code_chunk,
            "metadata": meta
        })

    return build_prompt(user_request, chunked_docs, current_file_path)

def choose_files_by_summary(instruction, metas, max_files=5):
    file_list_text = "\n".join(
        f"{i+1}. {m['path']}: {m.get('summary', '')}" for i, m in enumerate(metas)
    )

    prompt = f"""
    You are an assistant that helps find relevant files for a programming task.

    User instruction: "{instruction}"

    Here are the files in the project with summaries:

    {file_list_text}

    Please rank the files by relevance to the instruction and return the top {max_files} paths as a JSON list.
    """

    print(f"Instruction passed to search: {instruction}")

    response = client.chat.completions.create(
        model="gpt-5-nano",
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        ranked_paths = json.loads(response.choices[0].message.content)

        # reorder metas in the order returned
        ranked_metas = []
        seen = set()
        for path in ranked_paths:
            match = next((m for m in metas if m["path"] == path), None)
            if match and path not in seen:
                ranked_metas.append(match)
                seen.add(path)

        # If fewer than max_files found, pad with remaining metas
        for m in metas:
            if m["path"] not in seen:
                ranked_metas.append(m)

        return ranked_metas[:max_files]  # return the metas reordered
    except Exception as e:
        print("Ranking parse failed:", e)
        return metas[:max_files]

def build_prompt(user_request, chunked_docs, current_file_path):
    sections = []
    for chunk in chunked_docs:
        meta = chunk.get('metadata', {})
        path = meta.get('path', current_file_path)
        name = meta.get('chunk_name', '<unnamed chunk>')
        start = meta.get('start_line', '?')
        end = meta.get('end_line', '?')
        code = chunk.get('code', '')

        sections.append(
            f"[TARGET] File: {path}\nChunk: {name} (lines {start}-{end})\n{code}"
        )

    joined_code = "\n\n---\n\n".join(sections)

    return [
        {
            "role": "system",
            "content": (
                "You can modify any [TARGET] chunks across multiple files.\n"
                "For each modified chunk, return it with the file path included in this exact format:\n\n"
                "--- FILE: <file_path> ---\n"
                "--- CHUNK START: lines <start_line>-<end_line> ---\n"
                "<updated code here>\n"
                "--- CHUNK END ---\n\n"
                "Do NOT include explanations, comments outside the code, or code fences."
            )
        },
        {
            "role": "user",
            "content": f"{user_request}\n\nRelevant code snippets:\n{joined_code}"
        }
    ]
