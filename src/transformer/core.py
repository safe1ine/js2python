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
        for param in params:
            if param.get("type") != "Identifier":
                raise TransformError("Only simple identifier params are supported.", param)
            args.append(ast.arg(arg=param.get("name"), annotation=None, type_comment=None))
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

    def _transform_stmt_VariableDeclaration(self, node: Dict[str, Any]) -> List[ast.Assign]:
        if node.get("kind") != "var":
            raise TransformError("Only `var` declarations are supported in ES5 mode.", node)
        assignments: List[ast.Assign] = []
        for declarator in node.get("declarations", []):
            target_node = declarator.get("id")
            value_node = declarator.get("init")
            target = self._transform_identifier(target_node, ctx=ast.Store())
            value = (
                self._transform_expression(value_node) if value_node is not None else ast.Constant(None)
            )
            assignments.append(ast.Assign(targets=[target], value=value, type_comment=None))
        if not assignments:
            raise TransformError("Empty VariableDeclaration.", node)
        return assignments

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
            "WhileStatement": self._transform_stmt_WhileStatement,
            "DoWhileStatement": self._transform_stmt_DoWhileStatement,
            "SwitchStatement": self._transform_stmt_SwitchStatement,
            "BreakStatement": self._transform_stmt_BreakStatement,
            "ContinueStatement": self._transform_stmt_ContinueStatement,
            "TryStatement": self._transform_stmt_TryStatement,
            "ThrowStatement": self._transform_stmt_ThrowStatement,
        }

    @property
    def _expression_dispatch(self) -> Dict[str, Any]:
        return {
            "Identifier": self._transform_expr_Identifier,
            "Literal": self._transform_expr_Literal,
            "CallExpression": self._transform_expr_CallExpression,
            "MemberExpression": self._transform_expr_MemberExpression,
            "BinaryExpression": self._transform_expr_BinaryExpression,
            "LogicalExpression": self._transform_expr_LogicalExpression,
            "ObjectExpression": self._transform_expr_ObjectExpression,
            "ArrayExpression": self._transform_expr_ArrayExpression,
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
