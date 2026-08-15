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
        re.compile(r"^\s*import\s+([\w.]+)", re.M),
        re.compile(r"^\s*from\s+([\w.]+)\s+import", re.M),
    ],
    "javascript": [
        re.compile(r"""import\s+(?:[^'"]*?from\s+)?['"]([^'"]+)['"]"""),
        re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),
        re.compile(r"""export\s+[^'"]*?from\s+['"]([^'"]+)['"]"""),
    ],
    "go": [
        re.compile(r'^\s*import\s+(?:\w+\s+)?"([^"]+)"', re.M),
    ],
    "rust": [
        re.compile(r"^\s*(?:pub\s+)?use\s+([\w:]+)", re.M),
    ],
    "ocaml": [
        re.compile(r"^\s*open\s+([\w.]+)", re.M),
        re.compile(r"^\s*include\s+([\w.]+)", re.M),
    ],
    "java": [re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)", re.M)],
    "kotlin": [re.compile(r"^\s*import\s+([\w.]+)", re.M)],
    "c": [re.compile(r'#include\s+["<]([^">]+)[">]')],
    "cpp": [re.compile(r'#include\s+["<]([^">]+)[">]')],
    "ruby": [
        re.compile(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]""", re.M),
    ],
}
_PATTERNS["typescript"] = _PATTERNS["javascript"]

_GO_BLOCK = re.compile(r"import\s*\(([^)]*)\)", re.S)
_GO_BLOCK_LINE = re.compile(r'^\s*(?:\w+\s+)?"([^"]+)"', re.M)

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
        if spec.startswith("."):  # relative (js/ts/python style)
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
