"""Best-effort import extraction and resolution.

Explicitly lossy (regex-level, no parsing) and tagged as such in evidence.
Good enough for module fan-in/fan-out importance signals; never treated as a
complete dependency graph.
"""

from __future__ import annotations

import re
from collections import Counter

_PATTERNS: dict[str, list[re.Pattern]] = {
    "python": [
        re.compile(r"^[ \t]*import\s+([\w.]+)", re.M),
        re.compile(r"^[ \t]*from[ \t]+([\w.]+)[ \t]+import", re.M),
    ],
    # Match the module-string clauses directly rather than scanning forward
    # from `import`/`export` across the binding list for a `from` that may be
    # absent. A lazy `[^'"]*?from` scan reruns at every `import` keyword and is
    # O(n^2) on a file full of `import ` tokens; matching `from '...'` (and the
    # bare `import '...'` / `require(...)` forms) instead has no forward scan
    # and is linear. `from '...'` covers `import ... from`, `export ... from`,
    # and `export * from` in one pattern.
    "javascript": [
        re.compile(r"""\bfrom\s*['"]([^'"]+)['"]"""),
        re.compile(r"""\bimport\s*['"]([^'"]+)['"]"""),
        re.compile(r"""\brequire\(\s*['"]([^'"]+)['"]\s*\)"""),
    ],
    "go": [
        re.compile(r'^[ \t]*import\s+(?:\w+\s+)?"([^"]+)"', re.M),
    ],
    "rust": [
        re.compile(r"^[ \t]*(?:pub\s+)?use\s+([\w:]+)", re.M),
    ],
    "ocaml": [
        re.compile(r"^[ \t]*open\s+([\w.]+)", re.M),
        re.compile(r"^[ \t]*include\s+([\w.]+)", re.M),
    ],
    "java": [re.compile(r"^[ \t]*import\s+(?:static\s+)?([\w.]+)", re.M)],
    "kotlin": [re.compile(r"^[ \t]*import\s+([\w.]+)", re.M)],
    "c": [re.compile(r'#include\s+["<]([^">]+)[">]')],
    "cpp": [re.compile(r'#include\s+["<]([^">]+)[">]')],
    "ruby": [
        re.compile(r"""^[ \t]*require(?:_relative)?\s+['"]([^'"]+)['"]""", re.M),
    ],
}
_PATTERNS["typescript"] = _PATTERNS["javascript"]

# Exclude `(` from the block body so an unclosed `import(` cannot scan forward
# past the next parenthesis — otherwise `[^)]*` reruns to end-of-file at every
# `import(` token, O(n^2). Real Go import paths never contain a parenthesis.
_GO_BLOCK = re.compile(r"import\s*\(([^)(]*)\)", re.S)
_GO_BLOCK_LINE = re.compile(r'^[ \t]*(?:\w+\s+)?"([^"]+)"', re.M)

_JS_SUFFIXES = ("", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
                "/index.js", "/index.ts")

EDGE_CAP = 200
EXTERNAL_CAP = 30


def module_of(rel: str) -> str:
    """Directory-granularity module of a repo-relative path ('.' at root)."""
    return rel.rsplit("/", 1)[0] if "/" in rel else "."


def extract_imports(text: str, language: str) -> list[str]:
    found: list[str] = []
    for pattern in _PATTERNS.get(language, []):
        found.extend(m.group(1) for m in pattern.finditer(text))
    if language == "go":
        for block in _GO_BLOCK.finditer(text):
            found.extend(
                m.group(1) for m in _GO_BLOCK_LINE.finditer(block.group(1))
            )
    return found


class Resolver:
    """Maps import strings to repo-internal modules, best-effort."""

    def __init__(self, code_files: list[tuple[str, str]]):
        self.paths = {rel for rel, _ in code_files}
        # "a/b/c" (extension stripped) -> rel path; collisions resolve to
        # the alphabetically first path, deterministically.
        self.by_slug: dict[str, str] = {}
        self.by_stem: dict[str, str] = {}
        # "helpers.h" -> rel path, for file-with-extension specs
        # (#include "helpers.h", import "./x.js" fallthroughs).
        self.by_name: dict[str, str] = {}
        for rel, _ in sorted(code_files):
            slug = rel.rsplit(".", 1)[0]
            self.by_slug.setdefault(slug, rel)
            self.by_stem.setdefault(slug.rsplit("/", 1)[-1].lower(), rel)
            self.by_name.setdefault(rel.rsplit("/", 1)[-1].lower(), rel)
        # Every package directory, so a bare relative import ("from . import
        # x") resolves to the importer's own package, never a phantom module.
        self.dirs: set[str] = set()
        for rel in self.paths:
            parts = rel.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                self.dirs.add("/".join(parts[:i]))
        # Lowered: OCaml/Java-style specs capitalize what the filesystem
        # keeps lowercase (open Translate -> translate/).
        self.top_level = {
            p.split("/", 1)[0].rsplit(".", 1)[0].lower() for p in self.paths
        }

    def resolve(
        self,
        spec: str,
        importer_rel: str,
        language: str,
    ) -> tuple[str, str | None]:
        """Return ("internal", module) or ("external", top-level name)."""
        if spec.startswith("."):
            return self._resolve_relative(spec, importer_rel, language)

        # File-with-extension specs (C-family includes): by_name keys always
        # contain a dot, so bare module specs ("os", "lodash") can't match.
        name = spec.rsplit("/", 1)[-1].lower()
        if name in self.by_name:
            return "internal", module_of(self.by_name[name])

        slug = spec.replace(".", "/").replace("::", "/").rstrip("/")
        for known, rel in self.by_slug.items():
            if known == slug or known.endswith("/" + slug):
                return "internal", module_of(rel)
        stem = slug.rsplit("/", 1)[-1].lower()
        if stem in self.by_stem:
            return "internal", module_of(self.by_stem[stem])
        first = spec.replace("::", ".").split(".")[0].split("/")[0]
        if first.lower() in self.top_level:
            return "internal", first.lower()
        return "external", first or None

    def _resolve_relative(
        self,
        spec: str,
        importer_rel: str,
        language: str,
    ) -> tuple[str, str | None]:
        """Resolve a relative (js/ts/python style) spec against the importer."""
        base = module_of(importer_rel)
        segments = base.split("/") if base != "." else []
        if language == "python":
            level = len(spec) - len(spec.lstrip("."))
            for _ in range(max(0, level - 1)):
                segments = segments[:-1]
            remainder = spec[level:]
            if remainder:
                segments.extend(remainder.split("."))
        else:
            parts = spec.replace("\\", "/").split("/")
            for part in parts:
                if part in ("", "."):
                    continue
                if part == "..":
                    segments = segments[:-1]
                else:
                    segments.append(part)
        joined = "/".join(segments)
        for suffix in _JS_SUFFIXES:
            candidate = joined + suffix
            if candidate in self.paths or candidate.rsplit(".", 1)[0] in self.by_slug:
                hit = candidate if candidate in self.paths else self.by_slug[
                    candidate.rsplit(".", 1)[0]
                ]
                return "internal", module_of(hit)
        if joined in self.dirs:  # a package itself, not a file in one
            return "internal", joined
        return "internal", module_of(joined) if joined else None


def build_imports_section(file_imports: list[tuple[str, str, list[str]]],
                          code_files: list[tuple[str, str]]) -> dict:
    """file_imports: (path, language, import specs) per scanned file."""
    resolver = Resolver(code_files)
    edges: Counter = Counter()
    external: Counter = Counter()
    for rel, language, specs in file_imports:
        importer_module = module_of(rel)
        for spec in specs:
            kind, target = resolver.resolve(spec, rel, language)
            if target is None:
                continue
            if kind == "internal":
                if target != importer_module:
                    edges[(importer_module, target)] += 1
            else:
                external[target] += 1

    ranked_edges = sorted(edges.items(), key=lambda kv: (-kv[1], kv[0]))
    ranked_external = sorted(external.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "lossy": True,  # regex-level extraction; incomplete by design
        "internal_edges": [
            {"from": a, "to": b, "count": c}
            for (a, b), c in ranked_edges[:EDGE_CAP]
        ],
        "edges_truncated": max(0, len(ranked_edges) - EDGE_CAP),
        "external_top": [
            {"name": n, "count": c} for n, c in ranked_external[:EXTERNAL_CAP]
        ],
        "external_truncated": max(0, len(ranked_external) - EXTERNAL_CAP),
    }
