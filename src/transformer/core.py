"""
Core transformation logic that maps ES5 JavaScript AST nodes (as produced by
`esprima`) into Python's `ast` module representation.

Goal: provide a small but extensible foundation that later rules can build on.
The current implementation focuses on a subset of nodes required for simple
scripts (function declarations, basic expressions, control flow). Unsupported
constructs raise `TransformError` so callers can surface diagnostics or fall
back to manual handling.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


class TransformError(RuntimeError):
    """Raised when a node cannot be transformed into Python AST."""

    def __init__(self, message: str, node: Optional[Dict[str, Any]] = None):
        loc = ""
        if node and isinstance(node, dict):
            loc_meta = node.get("loc", {})
            start = loc_meta.get("start") or {}
            line = start.get("line")
            column = start.get("column")
            if line is not None and column is not None:
                loc = f" (line {line}, column {column})"
        super().__init__(f"{message}{loc}")
        self.node = node


@dataclass(frozen=True)
class TransformContext:
    """Contextual information available during node transformation."""

    source_name: str


@dataclass(frozen=True)
class TransformResult:
    module: ast.Module
    diagnostics: List[str]


class Transformer:
    """Visitor converting JS AST nodes into Python AST nodes."""

    def __init__(self, *, context: TransformContext):
        self.context = context
        self.diagnostics: List[str] = []

    def _format_location(self, node: Optional[Dict[str, Any]]) -> str:
        if not node or not isinstance(node, dict):
            return ""
        loc_meta = node.get("loc", {})
        start = loc_meta.get("start") or {}
        line = start.get("line")
        column = start.get("column")
        if line is None or column is None:
            return ""
        return f" (line {line}, column {column})"

    def _warn(self, message: str, node: Optional[Dict[str, Any]] = None) -> None:
        loc = self._format_location(node)
        self.diagnostics.append(f"{message}{loc}")

    # ------------------------------------------------------------------ helpers

    def transform_program(self, program: Dict[str, Any]) -> ast.Module:
        if program.get("type") != "Program":
            raise TransformError("Expected Program node at the root.", program)
        body_nodes: List[ast.stmt] = []
        for statement in program.get("body", []):
            body_nodes.extend(self._transform_statement(statement))
        module = ast.Module(body=body_nodes, type_ignores=[])
        ast.fix_missing_locations(module)
        return module

    def _transform_statement(self, node: Dict[str, Any]) -> List[ast.stmt]:
        handler = getattr(self, f"_transform_stmt_{node.get('type')}", None)
        if handler is None:
            raise TransformError(
                f"Unsupported statement node: {node.get('type')}", node=node
            )
        result = handler(node)
        if isinstance(result, list):
            return result
        return [result]

    def _transform_expression(self, node: Dict[str, Any]) -> ast.expr:
        handler = getattr(self, f"_transform_expr_{node.get('type')}", None)
        if handler is None:
            raise TransformError(
                f"Unsupported expression node: {node.get('type')}", node=node
            )
        return handler(node)

    def _transform_identifier(self, node: Dict[str, Any], ctx: ast.expr_context) -> ast.Name:
        if node.get("type") != "Identifier":
            raise TransformError("Expected Identifier.", node)
        return ast.Name(id=node.get("name"), ctx=ctx)

    def _transform_block(self, node: Dict[str, Any]) -> List[ast.stmt]:
        if node is None:
            return []
        if node.get("type") != "BlockStatement":
            raise TransformError("Expected BlockStatement.", node)
        statements: List[ast.stmt] = []
        for stmt in node.get("body", []):
            statements.extend(self._transform_statement(stmt))
        return statements

    # ----------------------------------------------------------- statement nodes

    def _transform_stmt_FunctionDeclaration(self, node: Dict[str, Any]) -> ast.FunctionDef:
        identifier = node.get("id")
        if not isinstance(identifier, dict):
            raise TransformError("FunctionDeclaration missing identifier.", node)

        args = self._transform_parameters(node.get("params", []))
        body = self._transform_block(node.get("body"))
        decorator_list: List[ast.expr] = []

        return ast.FunctionDef(
            name=identifier.get("name"),
            args=args,
            body=body,
            decorator_list=decorator_list,
            returns=None,
            type_comment=None,
        )

    def _transform_parameters(self, params: Iterable[Dict[str, Any]]) -> ast.arguments:
        args: List[ast.arg] = []
        defaults: List[ast.expr] = []
        kwonlyargs: List[ast.arg] = []
        kw_defaults: List[Optional[ast.expr]] = []
        vararg: Optional[ast.arg] = None
        kwarg: Optional[ast.arg] = None
        seen_default = False

        for param in params:
            param_type = param.get("type")
            if param_type == "Identifier":
                if seen_default:
                    raise TransformError(
                        "Parameters without defaults cannot follow parameters with defaults.",
                        param,
                    )
                args.append(ast.arg(arg=param.get("name"), annotation=None, type_comment=None))
            elif param_type == "AssignmentPattern":
                target = param.get("left")
                default_value = param.get("right")
                if not isinstance(target, dict) or target.get("type") != "Identifier":
                    raise TransformError(
                        "Only identifier assignment patterns are supported.", param
                    )
                args.append(ast.arg(arg=target.get("name"), annotation=None, type_comment=None))
                defaults.append(self._transform_expression(default_value))
                seen_default = True
            elif param_type == "RestElement":
                argument = param.get("argument")
                if not isinstance(argument, dict) or argument.get("type") != "Identifier":
                    raise TransformError("Rest parameter must be an identifier.", param)
                if vararg is not None:
                    raise TransformError("Multiple rest parameters are not supported.", param)
                vararg = ast.arg(arg=argument.get("name"), annotation=None, type_comment=None)
            else:
                raise TransformError(
                    f"Unsupported parameter pattern: {param_type}", node=param
                )

        return ast.arguments(
            posonlyargs=[],
            args=args,
            vararg=vararg,
            kwonlyargs=kwonlyargs,
            kw_defaults=kw_defaults,
            kwarg=kwarg,
            defaults=defaults,
        )
        return ast.arguments(
            posonlyargs=[],
            args=args,
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )

    def _transform_stmt_ReturnStatement(self, node: Dict[str, Any]) -> ast.Return:
        argument = node.get("argument")
        value = self._transform_expression(argument) if argument is not None else None
        return ast.Return(value=value)

    def _transform_stmt_ExpressionStatement(self, node: Dict[str, Any]) -> List[ast.stmt]:
        expression_node = node.get("expression")
        if expression_node is None:
            raise TransformError("ExpressionStatement missing expression.", node)
        if expression_node.get("type") == "AssignmentExpression":
            return [self._transform_assignment_expression(expression_node)]
        expression = self._transform_expression(expression_node)
        return [ast.Expr(value=expression)]

    def _transform_stmt_VariableDeclaration(self, node: Dict[str, Any]) -> List[ast.stmt]:
        statements: List[ast.stmt] = []
        for declarator in node.get("declarations", []):
            target_node = declarator.get("id")
            value_node = declarator.get("init")

            identifier_name = self._extract_identifier_name(target_node)

            if value_node is not None and value_node.get("type") == "ArrowFunctionExpression":
                if not identifier_name:
                    raise TransformError(
                        "Arrow function declarations require simple identifier targets.", declarator
                    )
                statements.append(
                    self._transform_arrow_function_declaration(identifier_name, value_node)
                )
                continue

            if value_node is not None and value_node.get("type") == "ClassExpression":
                if not identifier_name:
                    raise TransformError(
                        "Class expressions must assign to an identifier.", declarator
                    )
                class_def = self._transform_class_expression(value_node, identifier_name)
                statements.append(class_def)
                continue

            target = self._transform_assignment_target(target_node)
            value = (
                self._transform_expression(value_node) if value_node is not None else ast.Constant(None)
            )
            statements.append(ast.Assign(targets=[target], value=value, type_comment=None))

        if not statements:
            raise TransformError("Empty VariableDeclaration.", node)
        return statements

    def _transform_stmt_IfStatement(self, node: Dict[str, Any]) -> ast.If:
        test = self._transform_expression(node.get("test"))
        consequent_body = self._ensure_block_statements(node.get("consequent"))
        alternate = node.get("alternate")
        orelse = self._ensure_block_statements(alternate) if alternate else []
        return ast.If(test=test, body=consequent_body, orelse=orelse)

    def _ensure_block_statements(self, node: Any) -> List[ast.stmt]:
        if node is None:
            return []
        if node.get("type") == "BlockStatement":
            statements: List[ast.stmt] = []
            for stmt in node.get("body", []):
                statements.extend(self._transform_statement(stmt))
            return statements
        # Single statement without block braces.
        return self._transform_statement(node)

    def _expression_to_statements(self, node: Dict[str, Any]) -> List[ast.stmt]:
        if node is None:
            return []
        node_type = node.get("type")
        if node_type == "AssignmentExpression":
            return [self._transform_assignment_expression(node)]
        if node_type == "UpdateExpression":
            return [self._transform_update_expression(node)]
        expr = self._transform_expression(node)
        return [ast.Expr(value=expr)]

    def _extract_identifier_name(self, node: Dict[str, Any]) -> Optional[str]:
        if isinstance(node, dict) and node.get("type") == "Identifier":
            return node.get("name")
        return None

    def _transform_arrow_function_declaration(
        self, name: str, node: Dict[str, Any]
    ) -> ast.FunctionDef:
        args = self._transform_parameters(node.get("params", []))
        body = self._build_arrow_function_body(node.get("body"))
        return ast.FunctionDef(
            name=name,
            args=args,
            body=body,
            decorator_list=[],
            returns=None,
            type_comment=None,
        )

    def _build_arrow_function_body(self, body_node: Any) -> List[ast.stmt]:
        if isinstance(body_node, dict) and body_node.get("type") == "BlockStatement":
            return self._ensure_block_statements(body_node)
        if body_node is None:
            return [ast.Return(value=ast.Constant(value=None))]
        return [ast.Return(value=self._transform_expression(body_node))]

    def _transform_class_expression(
        self, node: Dict[str, Any], name: Optional[str] = None
    ) -> ast.ClassDef:
        if not name:
            raise TransformError("Anonymous class expressions are not supported yet.", node)
        return self._build_class_def(name, node)

    def _build_class_def(self, name: str, node: Dict[str, Any]) -> ast.ClassDef:
        bases: List[ast.expr] = []
        super_class = node.get("superClass")
        if super_class is not None:
            bases.append(self._transform_expression(super_class))

        body_elements: List[ast.stmt] = []
        class_body = node.get("body") or {}
        for element in class_body.get("body", []):
            body_elements.extend(self._transform_class_element(element))
        if not body_elements:
            body_elements.append(ast.Pass())

        return ast.ClassDef(
            name=name,
            bases=bases,
            keywords=[],
            body=body_elements,
            decorator_list=[],
        )

    def _transform_class_element(self, element: Dict[str, Any]) -> List[ast.stmt]:
        element_type = element.get("type")
        if element_type != "MethodDefinition":
            self._warn(f"Unsupported class element type: {element_type}", element)
            return [ast.Pass()]
        return [self._transform_method_definition(element)]

    def _transform_method_definition(self, element: Dict[str, Any]) -> ast.FunctionDef:
        kind = element.get("kind", "method")
        static = element.get("static", False)
        key = element.get("key")
        computed = element.get("computed", False)

        if computed:
            raise TransformError("Computed class method names are not supported.", element)

        if not isinstance(key, dict):
            raise TransformError("Class method key must be an identifier or literal.", element)

        if key.get("type") == "Identifier":
            method_name = key.get("name")
        elif key.get("type") == "Literal":
            method_name = str(key.get("value"))
        else:
            raise TransformError("Unsupported class method name.", key)

        if kind == "constructor":
            method_name = "__init__"

        if kind in {"get", "set"}:
            self._warn(
                f"Accessor '{kind}' emitted as regular method; manual review recommended.",
                element,
            )

        value = element.get("value") or {}
        if value.get("type") not in {"FunctionExpression", "ArrowFunctionExpression"}:
            raise TransformError("Method definition must wrap a function expression.", value)

        args = self._transform_parameters(value.get("params", []))
        if not static:
            args.args.insert(0, ast.arg(arg="self", annotation=None, type_comment=None))
        else:
            # staticmethod does not receive implicit self
            pass

        if value.get("type") == "ArrowFunctionExpression":
            body = self._build_arrow_function_body(value.get("body"))
        else:
            body = self._ensure_block_statements(value.get("body"))

        decorator_list: List[ast.expr] = []
        if static:
            decorator_list.append(ast.Name(id="staticmethod", ctx=ast.Load()))

        return ast.FunctionDef(
            name=method_name,
            args=args,
            body=body,
            decorator_list=decorator_list,
            returns=None,
            type_comment=None,
        )

    def _transform_for_loop_target(self, node: Dict[str, Any]) -> ast.expr:
        if node.get("type") == "VariableDeclaration":
            declarations = node.get("declarations", [])
            if len(declarations) != 1:
                raise TransformError("For-in/of supports a single declarator.", node)
            declarator = declarations[0]
            target_node = declarator.get("id")
            return self._transform_assignment_target(target_node)
        if node.get("type") == "Identifier":
            return self._transform_identifier(node, ctx=ast.Store())
        if node.get("type") == "MemberExpression":
            target = self._transform_expr_MemberExpression(node)
            if isinstance(target, (ast.Attribute, ast.Subscript)):
                target.ctx = ast.Store()
                return target
        raise TransformError("Unsupported for-loop target.", node)

    def _transform_stmt_ForStatement(self, node: Dict[str, Any]) -> List[ast.stmt]:
        init = node.get("init")
        test = node.get("test")
        update = node.get("update")
        body = node.get("body")

        statements: List[ast.stmt] = []
        if init is not None:
            if init.get("type") == "VariableDeclaration":
                statements.extend(self._transform_stmt_VariableDeclaration(init))
            else:
                statements.extend(self._expression_to_statements(init))

        test_expr = self._transform_expression(test) if test is not None else ast.Constant(True)
        body_statements = self._ensure_block_statements(body)
        if update is not None:
            body_statements.extend(self._expression_to_statements(update))

        loop = ast.While(test=test_expr, body=body_statements, orelse=[])
        statements.append(loop)
        return statements

    def _transform_stmt_ForInStatement(self, node: Dict[str, Any]) -> ast.For:
        target = self._transform_for_loop_target(node.get("left"))
        iter_expr = self._transform_expression(node.get("right"))
        body = self._ensure_block_statements(node.get("body"))
        return ast.For(target=target, iter=iter_expr, body=body, orelse=[])

    def _transform_stmt_ForOfStatement(self, node: Dict[str, Any]) -> ast.For:
        target = self._transform_for_loop_target(node.get("left"))
        iter_expr = self._transform_expression(node.get("right"))
        body = self._ensure_block_statements(node.get("body"))
        return ast.For(target=target, iter=iter_expr, body=body, orelse=[])

    def _transform_stmt_TryStatement(self, node: Dict[str, Any]) -> ast.Try:
        body = self._ensure_block_statements(node.get("block"))
        handlers: List[ast.ExceptHandler] = []
        handler_node = node.get("handler")
        if handler_node is not None:
            handlers.append(self._transform_catch_clause(handler_node))
        finalizer = node.get("finalizer")
        orelse = []
        if finalizer:
            final_body = self._ensure_block_statements(finalizer)
        else:
            final_body = []
        return ast.Try(
            body=body,
            handlers=handlers,
            orelse=orelse,
            finalbody=final_body,
        )

    def _transform_stmt_ClassDeclaration(self, node: Dict[str, Any]) -> ast.ClassDef:
        identifier = node.get("id")
        name = self._extract_identifier_name(identifier)
        if not name:
            raise TransformError("Class declarations require an identifier.", node)
        return self._build_class_def(name, node)

    def _transform_stmt_ExportDefaultDeclaration(self, node: Dict[str, Any]) -> List[ast.stmt]:
        declaration = node.get("declaration")
        if declaration is None:
            self._warn("export default without declaration is not supported.", node)
            return []
        if declaration.get("type") == "FunctionDeclaration":
            return [self._transform_stmt_FunctionDeclaration(declaration)]
        if declaration.get("type") == "ClassDeclaration":
            return [self._transform_stmt_ClassDeclaration(declaration)]
        if declaration.get("type") == "Identifier":
            target = declaration.get("name")
            return [ast.Assign(targets=[ast.Name(id="__default_export__", ctx=ast.Store())], value=ast.Name(id=target, ctx=ast.Load()))]
        self._warn("export default expression lowered to assignment.", declaration)
        return [
            ast.Assign(
                targets=[ast.Name(id="__default_export__", ctx=ast.Store())],
                value=self._transform_expression(declaration),
            )
        ]

    def _transform_stmt_ExportNamedDeclaration(self, node: Dict[str, Any]) -> List[ast.stmt]:
        declaration = node.get("declaration")
        if declaration is not None:
            return self._transform_statement(declaration)
        if node.get("specifiers"):
            self._warn("Export specifiers are noted but not emitted; consider manual __all__ edits.", node)
        return []

    def _transform_stmt_ImportDeclaration(self, node: Dict[str, Any]) -> List[ast.stmt]:
        source = node.get("source")
        module_name = source.get("value") if isinstance(source, dict) else None
        if not isinstance(module_name, str):
            raise TransformError("Import source must be a string literal.", node)

        specifiers = node.get("specifiers", [])
        statements: List[ast.stmt] = []
        named_specifiers = []
        for specifier in specifiers:
            spec_type = specifier.get("type")
            local = specifier.get("local")
            local_name = self._extract_identifier_name(local) if isinstance(local, dict) else None
            if spec_type == "ImportSpecifier":
                imported = specifier.get("imported")
                imported_name = self._extract_identifier_name(imported) if isinstance(imported, dict) else None
                alias = ast.alias(
                    name=imported_name or local_name,
                    asname=local_name if local_name != imported_name else None,
                )
                named_specifiers.append(alias)
            elif spec_type == "ImportDefaultSpecifier":
                if local_name is None:
                    raise TransformError("Default import requires a local identifier.", specifier)
                statements.append(
                    ast.Import(names=[ast.alias(name=module_name, asname=local_name if local_name != module_name else None)])
                )
            elif spec_type == "ImportNamespaceSpecifier":
                if local_name is None:
                    raise TransformError("Namespace import requires a local identifier.", specifier)
                statements.append(
                    ast.Import(names=[ast.alias(name=module_name, asname=local_name)])
                )
            else:
                self._warn(f"Unsupported import specifier: {spec_type}", specifier)

        if named_specifiers:
            statements.append(ast.ImportFrom(module=module_name, names=named_specifiers, level=0))

        if not statements:
            statements.append(ast.Import(names=[ast.alias(name=module_name, asname=None)]))

        return statements

    def _transform_catch_clause(self, node: Dict[str, Any]) -> ast.ExceptHandler:
        param = node.get("param")
        name = None
        exception_type = None
        if param is not None:
            if param.get("type") != "Identifier":
                raise TransformError("Catch parameter must be an Identifier.", node)
            name = param.get("name")
            exception_type = ast.Name(id="Exception", ctx=ast.Load())
        body = self._ensure_block_statements(node.get("body"))
        return ast.ExceptHandler(type=exception_type, name=name, body=body)

    def _transform_stmt_ThrowStatement(self, node: Dict[str, Any]) -> ast.Raise:
        argument = node.get("argument")
        if argument is None:
            raise TransformError("Throw statement missing argument.", node)
        exc = self._transform_expression(argument)
        return ast.Raise(exc=exc, cause=None)

    def _transform_stmt_WhileStatement(self, node: Dict[str, Any]) -> ast.While:
        test = self._transform_expression(node.get("test"))
        body = self._ensure_block_statements(node.get("body"))
        return ast.While(test=test, body=body, orelse=[])

    def _transform_stmt_DoWhileStatement(self, node: Dict[str, Any]) -> List[ast.stmt]:
        self._warn("do/while loop lowered to while; ensure side effects are compatible.", node)
        body_once = self._ensure_block_statements(node.get("body"))
        loop_body = self._ensure_block_statements(node.get("body"))
        test = self._transform_expression(node.get("test"))
        loop = ast.While(test=test, body=loop_body, orelse=[])
        return body_once + [loop]

    def _transform_stmt_SwitchStatement(self, node: Dict[str, Any]) -> List[ast.stmt]:
        discriminant = self._transform_expression(node.get("discriminant"))
        cases = node.get("cases", [])
        if not cases:
            return []

        top_if: Optional[ast.If] = None
        previous_if: Optional[ast.If] = None
        default_body: Optional[List[ast.stmt]] = None

        for switch_case in cases:
            case_body = self._transform_switch_case_body(switch_case.get("consequent", []))
            test = switch_case.get("test")
            if test is None:
                default_body = case_body
                continue
            comparison = ast.Compare(
                left=discriminant,
                ops=[ast.Eq()],
                comparators=[self._transform_expression(test)],
            )
            current_if = ast.If(test=comparison, body=case_body, orelse=[])
            if top_if is None:
                top_if = current_if
            else:
                assert previous_if is not None
                previous_if.orelse = [current_if]
            previous_if = current_if

        if top_if is None:
            return default_body or []
        if default_body is not None:
            assert previous_if is not None
            previous_if.orelse = default_body
        return [top_if]

    def _transform_switch_case_body(self, body_nodes: List[Dict[str, Any]]) -> List[ast.stmt]:
        statements: List[ast.stmt] = []
        for stmt in body_nodes:
            transformed = self._transform_statement(stmt)
            stop = False
            for item in transformed:
                if isinstance(item, ast.Break):
                    stop = True
                    break
                statements.append(item)
            if stop:
                break
        return statements

    # --------------------------------------------------------- expression nodes

    def _transform_expr_Identifier(self, node: Dict[str, Any]) -> ast.Name:
        return self._transform_identifier(node, ctx=ast.Load())

    def _transform_expr_Literal(self, node: Dict[str, Any]) -> ast.Constant:
        value = node.get("value")
        if node.get("raw") == "null":
            value = None
        return ast.Constant(value=value)

    def _transform_expr_CallExpression(self, node: Dict[str, Any]) -> ast.Call:
        callee = self._transform_expression(node.get("callee"))
        args = [self._transform_expression(arg) for arg in node.get("arguments", [])]
        return ast.Call(func=callee, args=args, keywords=[])

    def _transform_expr_NewExpression(self, node: Dict[str, Any]) -> ast.Call:
        callee = self._transform_expression(node.get("callee"))
        args = [self._transform_expression(arg) for arg in node.get("arguments", [])]
        return ast.Call(func=callee, args=args, keywords=[])

    def _transform_expr_MemberExpression(self, node: Dict[str, Any]) -> ast.expr:
        object_node = node.get("object")
        property_node = node.get("property")
        if node.get("computed"):
            # e.g. obj[expr]
            return ast.Subscript(
                value=self._transform_expression(object_node),
                slice=self._transform_expression(property_node),
                ctx=ast.Load(),
            )
        else:
            attr_name = (
                property_node.get("name")
                if isinstance(property_node, dict)
                else property_node
            )
            if not isinstance(property_node, dict):
                raise TransformError("MemberExpression property must be Identifier.", node)
            return ast.Attribute(
                value=self._transform_expression(object_node),
                attr=property_node.get("name"),
                ctx=ast.Load(),
            )

    def _transform_expr_BinaryExpression(self, node: Dict[str, Any]) -> ast.expr:
        operator = node.get("operator")
        left = self._transform_expression(node.get("left"))
        right = self._transform_expression(node.get("right"))

        if operator == "+":
            return ast.BinOp(left=left, op=ast.Add(), right=right)
        if operator == "-":
            return ast.BinOp(left=left, op=ast.Sub(), right=right)
        if operator == "*":
            return ast.BinOp(left=left, op=ast.Mult(), right=right)
        if operator == "/":
            return ast.BinOp(left=left, op=ast.Div(), right=right)
        if operator in {"===", "=="}:
            return ast.Compare(left=left, ops=[ast.Eq()], comparators=[right])
        if operator in {"!==", "!="}:
            return ast.Compare(left=left, ops=[ast.NotEq()], comparators=[right])
        if operator == ">":
            return ast.Compare(left=left, ops=[ast.Gt()], comparators=[right])
        if operator == ">=":
            return ast.Compare(left=left, ops=[ast.GtE()], comparators=[right])
        if operator == "<":
            return ast.Compare(left=left, ops=[ast.Lt()], comparators=[right])
        if operator == "<=":
            return ast.Compare(left=left, ops=[ast.LtE()], comparators=[right])

        raise TransformError(f"Unsupported binary operator: {operator}", node=node)

    def _transform_assignment_expression(self, node: Dict[str, Any]) -> ast.stmt:
        operator = node.get("operator")
        if operator != "=":
            aug_assign = self._maybe_create_augassign(node)
            if aug_assign is not None:
                return aug_assign
            raise TransformError(
                f"Assignment operator '{operator}' is not supported.", node=node
            )
        left_node = node.get("left")
        right_node = node.get("right")
        target = self._transform_assignment_target(left_node)
        value = self._transform_expression(right_node)
        return ast.Assign(targets=[target], value=value, type_comment=None)

    def _transform_assignment_target(self, node: Dict[str, Any]) -> ast.expr:
        node_type = node.get("type")
        if node_type == "Identifier":
            return self._transform_identifier(node, ctx=ast.Store())
        if node_type == "MemberExpression":
            member = self._transform_expr_MemberExpression(node)
            if isinstance(member, ast.Attribute):
                member.ctx = ast.Store()
                return member
            if isinstance(member, ast.Subscript):
                member.ctx = ast.Store()
                return member
        raise TransformError("Unsupported assignment target.", node=node)

    def _maybe_create_augassign(self, node: Dict[str, Any]) -> Optional[ast.AugAssign]:
        operator = node.get("operator")
        op_map = {
            "+=": ast.Add,
            "-=": ast.Sub,
            "*=": ast.Mult,
            "/=": ast.Div,
        }
        if operator not in op_map:
            return None
        target = self._transform_assignment_target(node.get("left"))
        value = self._transform_expression(node.get("right"))
        return ast.AugAssign(target=target, op=op_map[operator](), value=value)

    def _transform_expr_LogicalExpression(self, node: Dict[str, Any]) -> ast.BoolOp:
        operator = node.get("operator")
        left = self._transform_expression(node.get("left"))
        right = self._transform_expression(node.get("right"))
        if operator == "&&":
            return ast.BoolOp(op=ast.And(), values=[left, right])
        if operator == "||":
            return ast.BoolOp(op=ast.Or(), values=[left, right])
        raise TransformError(f"Unsupported logical operator: {operator}", node=node)

    def _transform_expr_ObjectExpression(self, node: Dict[str, Any]) -> ast.Dict:
        keys: List[Optional[ast.expr]] = []
        values: List[ast.expr] = []
        for prop in node.get("properties", []):
            if prop.get("type") != "Property":
                raise TransformError("Only simple object properties are supported.", prop)
            key_node = prop.get("key")
            value_node = prop.get("value")
            if prop.get("kind") != "init":
                raise TransformError("Getter/setter properties are not supported.", prop)
            if prop.get("computed"):
                keys.append(self._transform_expression(key_node))
            else:
                if key_node.get("type") == "Identifier":
                    keys.append(ast.Constant(key_node.get("name")))
                elif key_node.get("type") == "Literal":
                    keys.append(ast.Constant(key_node.get("value")))
                else:
                    raise TransformError("Unsupported property key.", prop)
            values.append(self._transform_expression(value_node))
        return ast.Dict(keys=keys, values=values)

    def _transform_expr_ArrayExpression(self, node: Dict[str, Any]) -> ast.List:
        elements = []
        for element in node.get("elements", []):
            if element is None:
                self._warn("Sparse array element converted to None.", node)
                elements.append(ast.Constant(value=None))
            else:
                elements.append(self._transform_expression(element))
        return ast.List(elts=elements, ctx=ast.Load())

    def _transform_expr_ThisExpression(self, node: Dict[str, Any]) -> ast.Name:
        return ast.Name(id="self", ctx=ast.Load())

    def _transform_expr_TemplateLiteral(self, node: Dict[str, Any]) -> ast.JoinedStr:
        values: List[ast.expr] = []
        quasis = node.get("quasis", [])
        expressions = node.get("expressions", [])
        for index, quasi in enumerate(quasis):
            cooked = (quasi.get("value") or {}).get("cooked")
            if cooked:
                values.append(ast.Constant(value=cooked))
            if index < len(expressions):
                expr = self._transform_expression(expressions[index])
                values.append(ast.FormattedValue(value=expr, conversion=-1, format_spec=None))
        if not values:
            values.append(ast.Constant(value=""))
        return ast.JoinedStr(values=values)

    def _transform_expr_ArrowFunctionExpression(self, node: Dict[str, Any]) -> ast.Lambda:
        body = node.get("body")
        if isinstance(body, dict) and body.get("type") == "BlockStatement":
            raise TransformError(
                "Arrow functions with block bodies are not supported in expression context.",
                node=node,
            )
        args = self._transform_parameters(node.get("params", []))
        return ast.Lambda(args=args, body=self._transform_expression(body))

    def _transform_update_expression(self, node: Dict[str, Any]) -> ast.AugAssign:
        argument = node.get("argument")
        operator = node.get("operator")
        prefix = node.get("prefix")
        if prefix is False:
            # Postfix update expressions evaluate to previous value. For statement updates
            # ignore the returned value and treat as side effect.
            pass
        if operator not in {"++", "--"}:
            raise TransformError(f"Unsupported update operator: {operator}", node=node)
        op = ast.Add() if operator == "++" else ast.Sub()
        target = self._transform_assignment_target(argument)
        return ast.AugAssign(target=target, op=op, value=ast.Constant(value=1))

    def _transform_stmt_BreakStatement(self, node: Dict[str, Any]) -> ast.Break:
        return ast.Break()

    def _transform_stmt_ContinueStatement(self, node: Dict[str, Any]) -> ast.Continue:
        return ast.Continue()

    # ---------------------------------------------------------------- utilities

    def transform_node(self, node: Dict[str, Any]) -> ast.AST:
        """Public entry for transforming any node by dispatching on its type."""
        node_type = node.get("type")
        if node_type == "Program":
            return self.transform_program(node)
        if node_type in self._statement_dispatch:
            return self._transform_statement(node)
        if node_type in self._expression_dispatch:
            return self._transform_expression(node)
        raise TransformError(f"Unsupported root node type: {node_type}", node=node)

    @property
    def _statement_dispatch(self) -> Dict[str, Any]:
        return {
            "FunctionDeclaration": self._transform_stmt_FunctionDeclaration,
            "ReturnStatement": self._transform_stmt_ReturnStatement,
            "ExpressionStatement": self._transform_stmt_ExpressionStatement,
            "VariableDeclaration": self._transform_stmt_VariableDeclaration,
            "IfStatement": self._transform_stmt_IfStatement,
            "ForStatement": self._transform_stmt_ForStatement,
            "ForInStatement": self._transform_stmt_ForInStatement,
            "ForOfStatement": self._transform_stmt_ForOfStatement,
            "WhileStatement": self._transform_stmt_WhileStatement,
            "DoWhileStatement": self._transform_stmt_DoWhileStatement,
            "SwitchStatement": self._transform_stmt_SwitchStatement,
            "BreakStatement": self._transform_stmt_BreakStatement,
            "ContinueStatement": self._transform_stmt_ContinueStatement,
            "TryStatement": self._transform_stmt_TryStatement,
            "ThrowStatement": self._transform_stmt_ThrowStatement,
            "ClassDeclaration": self._transform_stmt_ClassDeclaration,
            "ImportDeclaration": self._transform_stmt_ImportDeclaration,
            "ExportDefaultDeclaration": self._transform_stmt_ExportDefaultDeclaration,
            "ExportNamedDeclaration": self._transform_stmt_ExportNamedDeclaration,
        }

    @property
    def _expression_dispatch(self) -> Dict[str, Any]:
        return {
            "Identifier": self._transform_expr_Identifier,
            "Literal": self._transform_expr_Literal,
            "CallExpression": self._transform_expr_CallExpression,
            "NewExpression": self._transform_expr_NewExpression,
            "MemberExpression": self._transform_expr_MemberExpression,
            "BinaryExpression": self._transform_expr_BinaryExpression,
            "LogicalExpression": self._transform_expr_LogicalExpression,
            "ObjectExpression": self._transform_expr_ObjectExpression,
            "ArrayExpression": self._transform_expr_ArrayExpression,
            "ThisExpression": self._transform_expr_ThisExpression,
            "TemplateLiteral": self._transform_expr_TemplateLiteral,
            "ArrowFunctionExpression": self._transform_expr_ArrowFunctionExpression,
        }


def transform_program(
    program: Dict[str, Any], *, source_name: str = "<input>"
) -> TransformResult:
    """
    Convenience wrapper building a transformer instance and returning the Python module
    along with collected diagnostics.
    """
    transformer = Transformer(context=TransformContext(source_name=source_name))
    module = transformer.transform_program(program)
    return TransformResult(module=module, diagnostics=transformer.diagnostics)


__all__ = [
    "Transformer",
    "TransformContext",
    "TransformError",
    "TransformResult",
    "transform_program",
]
