from pathlib import Path

from emitter import EmitOptions, emit_module
from frontend import run_frontend
from transformer import transform_program


def _emit_js(relative_path: str, *, source_type: str = "script"):
    source_path = Path(relative_path)
    source = source_path.read_text(encoding="utf-8")
    frontend_result = run_frontend(
        source, source_name=str(source_path), source_type=source_type
    )
    assert frontend_result.parse.ast is not None
    transform_result = transform_program(frontend_result.parse.ast, source_name=str(source_path))
    emit_result = emit_module(transform_result.module, EmitOptions())
    return emit_result.source, transform_result.diagnostics


def test_emit_function_call():
    source, diagnostics = _emit_js("tests/cases/function_call.js")
    assert "def add(a, b)" in source
    assert "result = add(1, 2)" in source
    assert not diagnostics


def test_emit_try_catch():
    source, diagnostics = _emit_js("tests/cases/error_handling.js")
    assert "try:" in source
    assert "except Exception as err" in source or "except err" in source
    assert "raise err" in source
    assert isinstance(diagnostics, list)


def test_emit_class_and_template():
    source, _ = _emit_js("tests/cases/class_declaration.js")
    assert "class Person" in source
    assert "def __init__(self, name)" in source
    assert "Hello {self.name}" in source


def test_emit_module_imports():
    source, _ = _emit_js("tests/cases/module_import.js", source_type="module")
    assert "from path import join" in source
    assert "import fs" in source
    assert "def load(" in source
