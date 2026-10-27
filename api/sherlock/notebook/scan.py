"""The exporter's allowlist scan (TRD §7.7, PRD NB-11), run on every code cell before the file is
written: imports only from the allowlist, no network modules, no `subprocess`, no file writes, no
shell escapes. Two cells are exempt by tag: `requirements` (its pinned `%pip install` line) and
`load` (its one write of the UTF-8 copy). It also refuses text that looks like a secret, and any
configured key's actual value anywhere in the file (sources, embedded outputs and metadata), since
Token Factory keys (`v1.…`) don't match the generic pattern.
"""

import ast
import json
import re

ALLOWED_IMPORTS = {
    "pandas", "numpy", "re", "math", "datetime", "rapidfuzz", "dateparser", "ftfy",  # the sandbox's
    "duckdb", "matplotlib", "sklearn", "IPython", "json", "warnings",
}
EXEMPT_TAGS = {"requirements", "load"}
WRITE_ATTRS = {"write_text", "write_bytes", "to_csv", "to_parquet", "to_excel", "to_pickle", "to_json", "savefig",
               "to_feather", "to_hdf", "to_sql", "unlink", "rmdir", "touch", "chmod"}
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "subprocess", "socket", "requests", "urllib", "os",
                "sys", "shutil", "pathlib"}
SECRET = re.compile(r"(sk-[A-Za-z0-9]{16,}|LLM_API_KEY|sherlock_uid|Bearer\s+[A-Za-z0-9._-]{12,})")


class ScanError(ValueError):
    pass


def _check_code(source: str, where: str) -> None:
    lines = [ln for ln in source.splitlines() if not ln.lstrip().startswith(("%", "!"))]
    if len(lines) != len(source.splitlines()):
        raise ScanError(f"{where}: shell and magic commands are only allowed in the requirements cell")
    tree = ast.parse("\n".join(lines))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    raise ScanError(f"{where}: imports {a.name}, which isn't allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                raise ScanError(f"{where}: imports from {node.module}, which isn't allowed")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise ScanError(f"{where}: uses {node.id}, which isn't allowed")
        elif isinstance(node, ast.Attribute) and node.attr in WRITE_ATTRS:
            raise ScanError(f"{where}: writes a file ({node.attr})")


def _configured_secrets() -> list[str]:
    from sherlock.config import get_settings

    settings = get_settings()
    return [v for v in (settings.llm_api_key, settings.tavily_api_key) if v and len(v) >= 8]


def scan(nb, secrets: list[str] | None = None) -> None:
    text = json.dumps(nb)
    for value in _configured_secrets() if secrets is None else secrets:
        if value in text:
            raise ScanError("the notebook contains a configured API key")
    for i, cell in enumerate(nb.cells, 1):
        if SECRET.search(cell.source):
            raise ScanError(f"cell {i}: looks like it contains a secret or an identifier")
        if cell.cell_type != "code":
            continue
        tags = set(cell.get("metadata", {}).get("tags", []))
        if tags & EXEMPT_TAGS:
            if "requirements" in tags and not all(
                ln.startswith(("#", "%pip install")) or not ln.strip() for ln in cell.source.splitlines()
            ):
                raise ScanError(f"cell {i}: the requirements cell may only install the pinned packages")
            continue
        _check_code(cell.source, f"cell {i}")
