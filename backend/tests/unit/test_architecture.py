"""Structural test: packages depend only downwards (docs/ARCHITECTURE_RULES.md, rule 1).

Scans every import in the package, including the ones inside functions and under TYPE_CHECKING,
and checks it against the layer order. The violations that exist today are listed in
`KNOWN_VIOLATIONS`; each one has a follow-up that removes it, and the test fails when an entry is
no longer needed, so the list can only shrink.
"""

import ast
from pathlib import Path

import esfake

PACKAGE_DIR = Path(esfake.__file__).parent

# Lowest first. Packages on the same level may not import each other.
LAYERS: tuple[tuple[str, ...], ...] = (
    ("shared",),
    ("pipeline",),
    ("corpus",),
    ("evaluation",),
    ("api", "workers"),
    ("cli",),
)
LEVEL = {package: level for level, packages in enumerate(LAYERS) for package in packages}

# (importing module, imported package): why it exists and what removes it.
KNOWN_VIOLATIONS: dict[tuple[str, str], str] = {
    (
        "esfake.pipeline.similarity.internal_client",
        "api",
    ): "the /internal/embed contract lives in api; moves to a neutral module",
}


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imported_packages(tree: ast.AST) -> set[str]:
    """Top-level esfake packages imported anywhere in the tree."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
            if node.module == "esfake":
                names = [f"esfake.{alias.name}" for alias in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            if parts[0] == "esfake" and len(parts) > 1:
                found.add(parts[1])
    return found


def _dependencies() -> set[tuple[str, str]]:
    """(importing module, imported package) for every import that crosses packages."""
    found: set[tuple[str, str]] = set()
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        module = _module_name(path)
        if "." not in module:
            continue
        own = module.split(".")[1]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.update((module, package) for package in _imported_packages(tree) - {own})
    return found


def _violates(module: str, package: str) -> bool:
    importer = module.split(".")[1]
    return LEVEL[package] >= LEVEL[importer]


def test_every_package_is_in_a_layer() -> None:
    packages = {path.name for path in PACKAGE_DIR.iterdir() if (path / "__init__.py").exists()}
    assert packages == set(LEVEL)


def test_packages_only_import_from_lower_layers() -> None:
    violations = {key for key in _dependencies() if _violates(*key)}

    assert sorted(violations - set(KNOWN_VIOLATIONS)) == []


def test_known_violations_are_still_needed() -> None:
    violations = {key for key in _dependencies() if _violates(*key)}

    assert sorted(set(KNOWN_VIOLATIONS) - violations) == []


def test_the_scan_sees_imports_inside_functions() -> None:
    # Guards the guard: the CLI imports its dependencies lazily, so a scan limited to module
    # level would see almost none of them.
    cli_dependencies = {
        package for module, package in _dependencies() if module == "esfake.cli.main"
    }

    assert {"corpus", "evaluation", "pipeline"} <= cli_dependencies
