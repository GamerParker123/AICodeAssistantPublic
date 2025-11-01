import os

def clean_code_output(output: str) -> str:
    """
    Normalize model output by stripping optional triple-backtick fencing used in Markdown
    and trimming whitespace. This helps when the model returns code blocks.
    """
    output = output.strip()
    if output.startswith("```"):
        lines = output.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return output

def normalize_path(p):
    """Normalize and absolute-ify a file path."""
    return os.path.normpath(os.path.abspath(p))
