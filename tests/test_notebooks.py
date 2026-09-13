"""Notebooks are part of the deliverable, so they have to run and to say something."""

import json
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = sorted((ROOT / "notebooks").glob("*.ipynb"))


def _cells(path: Path, kind: str) -> list[str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return ["".join(cell["source"]) for cell in document["cells"] if cell["cell_type"] == kind]


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda path: path.stem)
def test_notebook_is_more_than_a_stub(path: Path):
    code = _cells(path, "code")
    prose = _cells(path, "markdown")
    assert len(code) >= 4, "a notebook that only loads a CSV is not a comparison notebook"
    assert len(prose) >= 4, "every code cell needs the question it answers"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda path: path.stem)
def test_notebook_executes_top_to_bottom(path: Path):
    """Run every code cell in order from the notebooks directory."""
    namespace: dict[str, object] = {"__name__": "__notebook__"}
    for index, source in enumerate(_cells(path, "code"), start=1):
        try:
            exec(compile(source, f"{path.name}[cell {index}]", "exec"), namespace)
        except Exception as error:  # pragma: no cover - failure detail is the point
            pytest.fail(f"{path.name} cell {index} failed: {error!r}")
    plt.close("all")


@pytest.fixture(autouse=True)
def _run_from_notebooks_directory(monkeypatch):
    monkeypatch.chdir(ROOT / "notebooks")
