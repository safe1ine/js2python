import ast
from pathlib import Path

from frontend import run_frontend
from transformer import transform_program


def _load_ast(relative_path: str, *, source_type: str = "script"):
    source_path = Path(relative_path)
    source = source_path.read_text(encoding="utf-8")
    frontend_result = run_frontend(
        source, source_name=str(source_path), analyze=True, source_type=source_type
    )
    assert frontend_result.parse.ast is not None
    return frontend_result.parse.ast


def test_transformer_handles_function_and_call():
    program = _load_ast("tests/cases/function_call.js")
    result = transform_program(program, source_name="function_call.js")
    module = result.module

    assert isinstance(module, ast.Module)
    assert len(module.body) == 3

    fn_def = module.body[0]
    assert isinstance(fn_def, ast.FunctionDef)
    assert fn_def.name == "add"
    assert [arg.arg for arg in fn_def.args.args] == ["a", "b"]
    assert isinstance(fn_def.body[0], ast.Return)
    assert isinstance(fn_def.body[0].value, ast.BinOp)

    assign_stmt = module.body[1]
    assert isinstance(assign_stmt, ast.Assign)
    target = assign_stmt.targets[0]
    assert isinstance(target, ast.Name) and target.id == "result"

    expr_stmt = module.body[2]
    assert isinstance(expr_stmt, ast.Expr)
    call = expr_stmt.value
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Attribute)
    assert call.func.attr == "log"


def test_transformer_handles_if_statements():
    program = _load_ast("tests/cases/control_if.js")
    result = transform_program(program, source_name="control_if.js")
    module = result.module

    assert isinstance(module, ast.Module)
    assert len(module.body) == 1

    fn_def = module.body[0]
    assert isinstance(fn_def, ast.FunctionDef)
    assert fn_def.name == "classify"

    body = fn_def.body
    assert isinstance(body[0], ast.Assign)  # var label;
    if_stmt = body[1]
    assert isinstance(if_stmt, ast.If)
    assert isinstance(if_stmt.test, ast.Compare)
    assert len(if_stmt.orelse) == 1
    elif_stmt = if_stmt.orelse[0]
    assert isinstance(elif_stmt, ast.If)
    assert isinstance(body[-1], ast.Return)


def test_transformer_handles_loops():
    program = _load_ast("tests/cases/loop_constructs.js")
    result = transform_program(program, source_name="loop_constructs.js")
    module = result.module

    assert isinstance(module, ast.Module)
    fn_def = module.body[0]
    assert isinstance(fn_def, ast.FunctionDef)

    assigns = [stmt for stmt in fn_def.body if isinstance(stmt, ast.Assign)]
    assert any(isinstance(stmt.value, ast.Constant) for stmt in assigns)

    loops = [stmt for stmt in fn_def.body if isinstance(stmt, ast.While)]
    assert len(loops) >= 2  # for loop lowered to while + while


def test_transformer_handles_switch():
    program = _load_ast("tests/cases/switch_case.js")
    result = transform_program(program, source_name="switch_case.js")
    module = result.module

    fn_def = module.body[0]
    assert isinstance(fn_def, ast.FunctionDef)

    if_nodes = [stmt for stmt in fn_def.body if isinstance(stmt, ast.If)]
    assert if_nodes, "switch should lower to a series of if statements"


def test_transformer_handles_try_catch_and_throw():
    program = _load_ast("tests/cases/error_handling.js")
    result = transform_program(program, source_name="error_handling.js")
    module = result.module

    fn_def = module.body[0]
    assert isinstance(fn_def, ast.FunctionDef)
    try_stmt = next(stmt for stmt in fn_def.body if isinstance(stmt, ast.Try))
    assert len(try_stmt.handlers) == 1
    handler = try_stmt.handlers[0]
    assert handler.name == "err"
    raise_stmt = next(
        stmt for stmt in handler.body if isinstance(stmt, ast.Raise)
    )
    assert isinstance(raise_stmt, ast.Raise)


def test_transformer_handles_object_and_array_literals():
    program = _load_ast("tests/cases/data_literals.js")
    result = transform_program(program, source_name="data_literals.js")
    module = result.module

    fn_def = module.body[0]
    assign_stmt = fn_def.body[0]
    assert isinstance(assign_stmt, ast.Assign)
    dict_value = assign_stmt.value
    assert isinstance(dict_value, ast.Dict)

    array_value = dict_value.values[2]
    assert isinstance(array_value, ast.List)
    assert result.diagnostics, "Expected diagnostics for sparse array handling"


def test_transformer_handles_arrow_function_declarations():
    program = _load_ast("tests/cases/arrow_function.js")
    result = transform_program(program, source_name="arrow_function.js")
    module = result.module

    functions = [stmt for stmt in module.body if isinstance(stmt, ast.FunctionDef)]
    names = {fn.name for fn in functions}
    assert {"double", "sum"} <= names

    sum_fn = next(fn for fn in functions if fn.name == "sum")
    assert [arg.arg for arg in sum_fn.args.args] == ["a", "b"]
    assert len(sum_fn.args.defaults) == 1


def test_transformer_handles_class_declaration():
    program = _load_ast("tests/cases/class_declaration.js")
    result = transform_program(program, source_name="class_declaration.js")
    module = result.module

    class_def = next(stmt for stmt in module.body if isinstance(stmt, ast.ClassDef))
    assert class_def.name == "Person"
    method_names = {stmt.name for stmt in class_def.body if isinstance(stmt, ast.FunctionDef)}
    assert "__init__" in method_names
    greet_fn = next(stmt for stmt in class_def.body if isinstance(stmt, ast.FunctionDef) and stmt.name == "greet")
    return_stmt = next(stmt for stmt in greet_fn.body if isinstance(stmt, ast.Return))
    assert isinstance(return_stmt.value, ast.JoinedStr)


def test_transformer_handles_module_imports_and_exports():
    program = _load_ast("tests/cases/module_import.js", source_type="module")
    result = transform_program(program, source_name="module_import.js")
    module = result.module

    import_statements = [stmt for stmt in module.body if isinstance(stmt, (ast.Import, ast.ImportFrom))]
    assert any(isinstance(stmt, ast.ImportFrom) for stmt in import_statements)
    assert any(isinstance(stmt, ast.Import) for stmt in import_statements)

    functions = [stmt for stmt in module.body if isinstance(stmt, ast.FunctionDef)]
    assert any(fn.name == "load" for fn in functions)
