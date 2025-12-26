from pathlib import Path
from typing import Dict, Set

import pytest

from analyzer import BindingKind, ScopeType
from frontend import run_frontend


def _binding_names(scope, kind: BindingKind) -> Set[str]:
    names: Set[str] = set()
    for name, bindings in scope.bindings.items():
        for binding in bindings:
            if binding.kind == kind:
                names.add(name)
    return names


def _collect_bindings_recursive(scope, kind: BindingKind) -> Set[str]:
    names = _binding_names(scope, kind)
    for child in scope.children:
        names |= _collect_bindings_recursive(child, kind)
    return names


def _find_function_scope(root_scope, function_name: str):
    for child in root_scope.children:
        node = child.node
        if not isinstance(node, dict):
            continue
        ident = node.get("id")
        if (
            node.get("type") == "FunctionDeclaration"
            and isinstance(ident, dict)
            and ident.get("name") == function_name
        ):
            return child
    raise AssertionError(f"Function scope for {function_name} not found")


TEST_CASES = [
    (
        "tests/cases/hello.js",
        {"hello"},
        {"hello": {"name"}},
        {"hello": set()},
    ),
    (
        "tests/cases/function_call.js",
        {"add", "result"},
        {"add": {"a", "b"}},
        {"add": set()},
    ),
    (
        "tests/cases/control_if.js",
        {"classify"},
        {"classify": {"x"}},
        {"classify": {"label"}},
    ),
    (
        "tests/cases/loop_constructs.js",
        {"sum"},
        {"sum": {"arr"}},
        {"sum": {"total", "i"}},
    ),
    (
        "tests/cases/switch_case.js",
        {"grade"},
        {"grade": {"score"}},
        {"grade": {"letter"}},
    ),
]


@pytest.mark.parametrize(
    "relative_path, expected_globals, expected_params, expected_locals", TEST_CASES
)
def test_frontend_handles_constructs(
    relative_path: str,
    expected_globals: Set[str],
    expected_params: Dict[str, Set[str]],
    expected_locals: Dict[str, Set[str]],
    tmp_path,
):
    source_path = Path(relative_path)
    source = source_path.read_text(encoding="utf-8")
    result = run_frontend(
        source,
        source_name=str(source_path),
        cache_dir=tmp_path,
    )

    assert result.parse.ast is not None
    assert result.parse.errors == []
    assert result.parse.ast["type"] == "Program"

    assert result.analysis is not None
    assert not result.analysis.issues

    root = result.analysis.root_scope
    root_names = set(root.bindings.keys())
    assert expected_globals <= root_names

    for func_name, params in expected_params.items():
        func_scope = _find_function_scope(root, func_name)
        parameter_names = _binding_names(func_scope, BindingKind.PARAMETER)
        assert params <= parameter_names
        local_names = _binding_names(func_scope, BindingKind.VAR)
        assert expected_locals.get(func_name, set()) <= local_names


def test_frontend_handles_let_const_block_scope(tmp_path):
    source_path = Path("tests/cases/let_const.js")
    source = source_path.read_text(encoding="utf-8")
    result = run_frontend(
        source,
        source_name=str(source_path),
        cache_dir=tmp_path,
    )

    fn_scope = _find_function_scope(result.analysis.root_scope, "counter")
    let_names = _binding_names(fn_scope, BindingKind.LET)
    const_names = _binding_names(fn_scope, BindingKind.CONST)
    assert {"total"} <= let_names
    assert {"step"} <= const_names

    block_scopes = [
        child for child in fn_scope.children if child.scope_type == ScopeType.BLOCK
    ]
    assert block_scopes, "expected block scope for if-statement"
    assert any(
        "inside" in _binding_names(block, BindingKind.LET) for block in block_scopes
    )


def test_frontend_handles_arrow_functions(tmp_path):
    source_path = Path("tests/cases/arrow_function.js")
    source = source_path.read_text(encoding="utf-8")
    result = run_frontend(
        source,
        source_name=str(source_path),
        cache_dir=tmp_path,
    )

    root = result.analysis.root_scope
    const_bindings = _binding_names(root, BindingKind.CONST)
    assert {"double", "sum"} <= const_bindings

    arrow_scopes = [
        child
        for child in root.children
        if child.scope_type == ScopeType.FUNCTION
        and child.node.get("type") == "ArrowFunctionExpression"
    ]
    param_sets = [
        _binding_names(scope, BindingKind.PARAMETER) for scope in arrow_scopes
    ]
    assert any("value" in params for params in param_sets)
    assert any({"a", "b"} <= params for params in param_sets)


def test_frontend_handles_class_declaration(tmp_path):
    source_path = Path("tests/cases/class_declaration.js")
    source = source_path.read_text(encoding="utf-8")
    result = run_frontend(
        source,
        source_name=str(source_path),
        cache_dir=tmp_path,
    )

    root = result.analysis.root_scope
    class_bindings = _binding_names(root, BindingKind.CLASS)
    assert "Person" in class_bindings
    func_scope = _find_function_scope(root, "makePerson")
    assert "makePerson" in _binding_names(root, BindingKind.FUNCTION)

    class_scope = next(
        child
        for child in root.children
        if child.scope_type == ScopeType.CLASS and child.node.get("id", {}).get("name") == "Person"
    )
    constructor_scope = next(
        child
        for child in class_scope.children
        if child.scope_type == ScopeType.FUNCTION
        and child.node.get("type") in {"FunctionExpression", "ArrowFunctionExpression"}
    )
    assert "name" in _binding_names(constructor_scope, BindingKind.PARAMETER)


def test_frontend_handles_imports_exports(tmp_path):
    source_path = Path("tests/cases/module_import.js")
    source = source_path.read_text(encoding="utf-8")
    result = run_frontend(
        source,
        source_name=str(source_path),
        cache_dir=tmp_path,
        source_type="module",
    )

    root = result.analysis.root_scope
    import_bindings = _binding_names(root, BindingKind.IMPORT)
    assert {"join", "fs"} <= import_bindings
    function_bindings = _binding_names(root, BindingKind.FUNCTION)
    assert any(name for name in function_bindings)
