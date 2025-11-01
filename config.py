import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PROJECT_PATH = os.getenv("PROJECT_PATH")
CHROMA_DB_PATH = "chroma"

EXCLUDE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".json", ".html", ".css"}