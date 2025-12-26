from pathlib import Path
from typing import Dict, Set

import pytest

from analyzer import BindingKind
from frontend import run_frontend


def _binding_names(scope, kind: BindingKind) -> Set[str]:
    names: Set[str] = set()
    for name, bindings in scope.bindings.items():
        for binding in bindings:
            if binding.kind == kind:
                names.add(name)
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
