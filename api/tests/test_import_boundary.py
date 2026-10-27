"""The removed surfaces stay removed (docs/plans/focus-cleaning-and-query.md §7.1): no module under
`sherlock/` imports the dashboard, widgets, stories, canvas or Flow code or their jobs, at module level
or inside a function, and none of those modules exists on disk."""

import ast
import textwrap
from pathlib import Path

import sherlock

PACKAGE = Path(sherlock.__file__).resolve().parent
GONE = ("sherlock.dashboard", "sherlock.widgets", "sherlock.stories", "sherlock.canvas", "sherlock.agent.flow",
        "sherlock.jobs.build", "sherlock.jobs.stories", "sherlock.jobs.cascade")


def _package(path: Path) -> str:
    """The package a file's relative imports start from."""
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    return ".".join(parts[:-1])


def _imports(source: str, package: str):
    """Every module name an import in the source names (anywhere, functions too), relative imports resolved."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join(anchor + ([base] if base else []))
            yield base
            yield from (f"{base}.{alias.name}" for alias in node.names)  # `from sherlock import widgets`


def _gone(name: str) -> bool:
    return any(name == g or name.startswith(g + ".") for g in GONE)


def test_no_module_imports_a_removed_surface():
    found = [f"{path.relative_to(PACKAGE.parent).as_posix()}: {name}"
             for path in sorted(PACKAGE.rglob("*.py"))
             for name in _imports(path.read_text(encoding="utf-8"), _package(path)) if _gone(name)]
    assert found == []


def test_the_removed_modules_are_not_on_disk():
    left = []
    for name in GONE:
        rel = Path(*name.split(".")[1:])
        for candidate in (PACKAGE / rel, PACKAGE / rel.with_suffix(".py")):
            if candidate.exists():
                left.append(candidate.relative_to(PACKAGE.parent).as_posix())
    assert left == []


def test_the_walk_catches_every_form_of_import():
    """The check itself: absolute, `from` package, relative and function-level imports are all caught."""
    source = textwrap.dedent("""
        import sherlock.widgets.spec
        from sherlock import stories
        from ..dashboard import builder
        from . import flow

        def later():
            from sherlock.jobs.cascade import queue_cascade
    """)
    assert sorted(n for n in _imports(source, "sherlock.agent") if _gone(n)) == [
        "sherlock.agent.flow", "sherlock.dashboard", "sherlock.dashboard.builder", "sherlock.jobs.cascade",
        "sherlock.jobs.cascade.queue_cascade", "sherlock.stories", "sherlock.widgets.spec"]
    assert not [n for n in _imports("from sherlock.query import compile\nimport sherlock.jobs.clean\n", "sherlock") if _gone(n)]
