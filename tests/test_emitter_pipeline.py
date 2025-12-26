from pathlib import Path

from emitter import EmitOptions, emit_module
from frontend import run_frontend
from transformer import transform_program


def _emit_js(relative_path: str):
    source_path = Path(relative_path)
    source = source_path.read_text(encoding="utf-8")
    frontend_result = run_frontend(source, source_name=str(source_path))
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
