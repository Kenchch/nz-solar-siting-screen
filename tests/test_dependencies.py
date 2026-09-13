"""Every third-party import must be declared, including the lazy ones.

scipy and rasterio both reached main without being declared: scipy broke CI at
the study step, and rasterio did not break anything because both of its callers
import it inside a function and neither runs in CI. A lazy import is still a
dependency.
"""

import ast
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
SOURCES = sorted(
    path
    for directory in ("src", "scripts", "tests")
    for path in (ROOT / directory).rglob("*.py")
)
LOCAL = {"nz_solar_siting"}


def _declared() -> set[str]:
    project = PYPROJECT["project"]
    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    names = set()
    for requirement in requirements:
        name = requirement.split(";")[0]
        for separator in (">=", "==", "<=", "~=", ">", "<", "[", " "):
            name = name.split(separator)[0]
        names.add(name.strip().lower().replace("-", "_"))
    # Distribution name to import name, where they differ.
    aliases = {"pyyaml": "yaml", "pillow": "pil"}
    return {aliases.get(name, name) for name in names}


def _imported() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""] if node.level == 0 else []
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if not top or top in sys.stdlib_module_names or top in LOCAL:
                    continue
                found.setdefault(top, []).append(path.relative_to(ROOT).as_posix())
    return found


def test_every_third_party_import_is_declared():
    declared = _declared()
    undeclared = {
        module: sorted(set(files))
        for module, files in _imported().items()
        if module.lower() not in declared
    }
    assert not undeclared, f"imported but not declared in pyproject.toml: {undeclared}"


@pytest.mark.parametrize("module", ["scipy", "rasterio"])
def test_the_lazily_imported_dependencies_are_declared(module: str):
    """These two are imported inside functions, so nothing fails at import time."""
    assert module in _declared()


def test_the_conda_environment_matches_the_project_dependencies():
    """environment.yml is the other install path and drifts silently."""
    text = (ROOT / "environment.yml").read_text(encoding="utf-8").lower()
    for name in _declared():
        # yaml and pil are import names; conda knows them by their package names.
        conda_name = {"yaml": "pyyaml", "pil": "pillow"}.get(name, name)
        assert conda_name.replace("_", "-") in text, f"{conda_name} missing from environment.yml"
