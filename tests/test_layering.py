# the one-way layering, checked by walking every import under mahad/
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "mahad"
QT = ("PySide6", "pyqtgraph")
# the read models the worker fills and the window renders: the only data modules the UI may import
VIEW_MODELS = ("mahad.data.symbols", "mahad.data.portfolio_view", "mahad.data.context_view")


def _within(target: str, prefix: str) -> bool:
    return target == prefix or target.startswith(prefix + ".")


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> list[str]:
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join(up + ([base] if base else []))
            out.extend(f"{base}.{alias.name}" if base else alias.name for alias in node.names)
    return out


def _layer_imports(layer: str) -> dict[str, list[str]]:
    root = PACKAGE / layer if (PACKAGE / layer).is_dir() else PACKAGE
    files = sorted(root.rglob("*.py")) if root != PACKAGE else [PACKAGE / f"{layer}.py"]
    return {p.relative_to(ROOT).as_posix(): _imports(p) for p in files}


def test_the_ui_imports_only_the_read_models_from_the_data_layer():
    for path, targets in _layer_imports("ui").items():
        for target in targets:
            if _within(target, "mahad.data"):
                assert any(_within(target, vm) for vm in VIEW_MODELS), f"{path} imports {target}"


def test_the_engine_and_data_layers_never_import_upwards():
    for layer in ("engine", "data"):
        for path, targets in _layer_imports(layer).items():
            for target in targets:
                assert not _within(target, "mahad.ui"), f"{path} imports {target}"
                assert not _within(target, "mahad.worker"), f"{path} imports {target}"


def test_the_worker_never_imports_the_ui():
    for path, targets in _layer_imports("worker").items():
        for target in targets:
            assert not _within(target, "mahad.ui"), f"{path} imports {target}"


def test_the_engine_and_the_report_import_no_qt():
    modules = {**_layer_imports("engine"), **_layer_imports("report")}
    assert "mahad/report.py" in modules and any(p.startswith("mahad/engine/") for p in modules)
    for path, targets in modules.items():
        for target in targets:
            assert not any(_within(target, qt) for qt in QT), f"{path} imports {target}"
