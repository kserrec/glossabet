"""Source-level tripwires for direct violations of documented trust promises.

These tests inspect current package syntax for selected imports, calls, path
mutation, and ``shell=`` arguments. They catch straightforward regressions
such as adding a network module, ``eval()``, or ``shell=True``. They do not
prove the absence of indirect, dynamically resolved, aliased, native, or
otherwise syntactically obscured behavior; runtime design and review remain
part of enforcing the broader promises in SECURITY.md, README.md, and
PRIVACY.md.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "glossabet"

NETWORK_MODULES = {
    "socket", "ssl", "urllib", "http", "ftplib", "smtplib", "poplib",
    "imaplib", "nntplib", "telnetlib", "xmlrpc", "webbrowser", "socketserver",
    "asyncio", "select", "selectors", "requests", "urllib3", "httpx",
}
DYNAMIC_CODE = {"eval", "exec", "compile", "__import__"}
DYNAMIC_IMPORT_MODULES = {"runpy", "pkgutil", "imp"}
IMPORTLIB_ALLOWED = {"resources", "metadata"}
# The only modules allowed to spawn processes, and only through the one
# hardened invocation each: git for the freshness stamp, `<glossabet>
# --version` when persisting a hook.
SUBPROCESS_ALLOWED = {
    PACKAGE / "runtime" / "git_state.py",
    PACKAGE / "install" / "claude_plugin.py",
}


def _engine_modules() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE.rglob("*.py")
        if "_skill" not in path.parts
        and not any(
            part == ".env"
            or part.endswith(".env")
            or part.startswith(".env.")
            or ".env." in part
            for part in path.relative_to(PACKAGE).parts
        )
    )


def _imported_roots(tree: ast.AST) -> dict[str, list[str]]:
    """{root module: [full names]} for every import statement."""
    found: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.setdefault(alias.name.split(".")[0], []).append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [f"{node.module}.{alias.name}" for alias in node.names]
            found.setdefault(node.module.split(".")[0], []).extend(names)
    return found


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
        return ".".join(reversed(parts))
    return ""


def test_engine_never_imports_a_network_capability():
    offenders = {}
    for path in _engine_modules():
        roots = _imported_roots(ast.parse(path.read_text(encoding="utf-8")))
        hit = sorted(name for root, names in roots.items() if root in NETWORK_MODULES for name in names)
        if hit:
            offenders[str(path.relative_to(ROOT))] = hit
    assert offenders == {}, offenders


def test_engine_never_evaluates_code_or_imports_dynamically():
    offenders = {}
    for path in _engine_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = []
        roots = _imported_roots(tree)
        for root, names in roots.items():
            if root in DYNAMIC_IMPORT_MODULES:
                hits.extend(names)
            if root == "importlib":
                for name in names:
                    leaf = name.split(".")[1] if "." in name else ""
                    if leaf not in IMPORTLIB_ALLOWED:
                        hits.append(name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name in DYNAMIC_CODE or name in {
                    "importlib.import_module", "builtins.eval", "builtins.exec",
                    "builtins.__import__", "runpy.run_path", "runpy.run_module",
                }:
                    hits.append(f"{name}() at line {node.lineno}")
        if hits:
            offenders[str(path.relative_to(ROOT))] = sorted(hits)
    assert offenders == {}, offenders


def test_engine_spawns_processes_only_where_documented_and_never_through_a_shell():
    offenders = {}
    for path in _engine_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = []
        roots = _imported_roots(tree)
        for root in ("subprocess", "os",):
            for name in roots.get(root, []):
                if root == "subprocess" and path not in SUBPROCESS_ALLOWED:
                    hits.append(f"imports {name}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name in {"os.system", "os.popen", "os.execv", "os.execvp", "os.execl",
                        "os.execlp", "os.execve", "os.execvpe", "os.spawnv",
                        "os.spawnl", "os.spawnvp", "os.posix_spawn", "os.fork"}:
                hits.append(f"{name}() at line {node.lineno}")
            # Any call carrying a `shell=` keyword that is not literally
            # False — however subprocess was imported or aliased.
            for keyword in node.keywords:
                if keyword.arg == "shell" and not (
                    isinstance(keyword.value, ast.Constant) and keyword.value.value is False
                ):
                    hits.append(f"{name or '<call>'}(shell=...) at line {node.lineno}")
        if hits:
            offenders[str(path.relative_to(ROOT))] = sorted(hits)
    assert offenders == {}, offenders


def test_engine_never_imports_the_repository_it_analyzes():
    """No `sys.path` mutation and no import machinery in the engine (the
    plugin runner, which does insert the bundled wheel, lives outside the
    package): the analyzed repository's code is text, never executed."""
    offenders = {}
    for path in _engine_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name in {"sys.path.insert", "sys.path.append", "sys.path.extend",
                            "site.addsitedir"}:
                    hits.append(f"{name}() at line {node.lineno}")
        if hits:
            offenders[str(path.relative_to(ROOT))] = sorted(hits)
    assert offenders == {}, offenders
