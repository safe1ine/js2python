"""
Scope analysis for ES5 JavaScript ASTs.

The analyzer walks an esprima-compatible AST, builds a tree of lexical scopes,
and records bindings introduced by `var`, `function`, and function parameters.
It flags potentially problematic constructs (`with`, `eval`) that complicate
static translation. The resulting scope metadata enables subsequent phases to
reason about identifier resolution during JS → Python conversion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional


class ScopeType(str, Enum):
    GLOBAL = "global"
    FUNCTION = "function"
    CATCH = "catch"


class BindingKind(str, Enum):
    VAR = "var"
    FUNCTION = "function"
    PARAMETER = "parameter"
    CATCH_PARAMETER = "catch_parameter"


@dataclass(frozen=True)
class SourcePosition:
    line: Optional[int]
    column: Optional[int]


@dataclass(frozen=True)
class Binding:
    """Represents a single identifier binding within a scope."""

    name: str
    kind: BindingKind
    loc: SourcePosition
    node: Dict[str, Any]


@dataclass
class Scope:
    """A lexical scope containing zero or more bindings and child scopes."""

    scope_id: str
    scope_type: ScopeType
    node: Dict[str, Any]
    parent: Optional["Scope"] = None
    bindings: Dict[str, List[Binding]] = field(default_factory=dict)
    children: List["Scope"] = field(default_factory=list)

    def add_binding(self, binding: Binding) -> None:
        """Register a binding within the current scope."""
        self.bindings.setdefault(binding.name, []).append(binding)

    def add_child(self, child: "Scope") -> None:
        self.children.append(child)


@dataclass(frozen=True)
class AnalysisIssue:
    code: str
    message: str
    loc: SourcePosition


@dataclass(frozen=True)
class AnalysisResult:
    source_name: str
    root_scope: Scope
    issues: List[AnalysisIssue]

    def flatten_scopes(self) -> Iterable[Scope]:
        """Yield scopes in depth-first order."""
        stack = [self.root_scope]
        while stack:
            scope = stack.pop()
            yield scope
            stack.extend(reversed(scope.children))


class _BindingAnalyzer:
    def __init__(self, source_name: str) -> None:
        self._source_name = source_name
        self._scope_counter = 0
        self._issues: List[AnalysisIssue] = []

    def analyze(self, ast: Dict[str, Any]) -> AnalysisResult:
        root_scope = self._new_scope(ScopeType.GLOBAL, ast, parent=None)
        self._visit(ast, root_scope)
        return AnalysisResult(
            source_name=self._source_name,
            root_scope=root_scope,
            issues=self._issues,
        )

    # ------------------------------------------------------------------ helpers

    def _new_scope(
        self, scope_type: ScopeType, node: Dict[str, Any], parent: Optional[Scope]
    ) -> Scope:
        scope_id = f"S{self._scope_counter}"
        self._scope_counter += 1
        scope = Scope(scope_id=scope_id, scope_type=scope_type, node=node, parent=parent)
        if parent:
            parent.add_child(scope)
        return scope

    @staticmethod
    def _source_position(node: Dict[str, Any]) -> SourcePosition:
        loc = node.get("loc") or {}
        start = loc.get("start") or {}
        return SourcePosition(
            line=start.get("line"),
            column=start.get("column"),
        )

    def _add_issue(self, code: str, message: str, node: Dict[str, Any]) -> None:
        self._issues.append(
            AnalysisIssue(code=code, message=message, loc=self._source_position(node))
        )

    def _visit(self, node: Any, scope: Scope) -> None:
        if node is None:
            return
        if isinstance(node, list):
            for element in node:
                self._visit(element, scope)
            return
        if not isinstance(node, dict):
            return

        handler = getattr(self, f"_visit_{node.get('type')}", None)
        if handler:
            handler(node, scope)
        else:
            self._generic_visit(node, scope)

    def _generic_visit(self, node: Dict[str, Any], scope: Scope) -> None:
        for key, value in node.items():
            if key in {"loc", "range"}:
                continue
            self._visit(value, scope)

    # ----------------------------------------------------------------- visitors

    def _visit_Program(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit(node.get("body", []), scope)

    def _visit_BlockStatement(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit(node.get("body", []), scope)

    def _visit_VariableDeclaration(self, node: Dict[str, Any], scope: Scope) -> None:
        for declarator in node.get("declarations", []):
            self._visit_VariableDeclarator(declarator, scope)

    def _visit_VariableDeclarator(self, node: Dict[str, Any], scope: Scope) -> None:
        identifier = node.get("id")
        if isinstance(identifier, dict) and identifier.get("type") == "Identifier":
            binding = Binding(
                name=identifier.get("name"),
                kind=BindingKind.VAR,
                loc=self._source_position(identifier),
                node=identifier,
            )
            scope.add_binding(binding)
        # Visit initializer to catch nested functions etc.
        self._visit(node.get("init"), scope)

    def _visit_FunctionDeclaration(self, node: Dict[str, Any], scope: Scope) -> None:
        identifier = node.get("id")
        if isinstance(identifier, dict) and identifier.get("type") == "Identifier":
            scope.add_binding(
                Binding(
                    name=identifier.get("name"),
                    kind=BindingKind.FUNCTION,
                    loc=self._source_position(identifier),
                    node=identifier,
                )
            )
        function_scope = self._new_scope(ScopeType.FUNCTION, node, scope)
        for param in node.get("params", []):
            self._register_parameter(param, function_scope)
        self._visit(node.get("body"), function_scope)

    def _visit_FunctionExpression(self, node: Dict[str, Any], scope: Scope) -> None:
        function_scope = self._new_scope(ScopeType.FUNCTION, node, scope)
        identifier = node.get("id")
        if isinstance(identifier, dict) and identifier.get("type") == "Identifier":
            # Named function expressions bind the name within the inner scope.
            function_scope.add_binding(
                Binding(
                    name=identifier.get("name"),
                    kind=BindingKind.FUNCTION,
                    loc=self._source_position(identifier),
                    node=identifier,
                )
            )
        for param in node.get("params", []):
            self._register_parameter(param, function_scope)
        self._visit(node.get("body"), function_scope)

    def _visit_ReturnStatement(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit(node.get("argument"), scope)

    def _visit_ExpressionStatement(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit(node.get("expression"), scope)

    def _visit_CallExpression(self, node: Dict[str, Any], scope: Scope) -> None:
        callee = node.get("callee")
        if (
            isinstance(callee, dict)
            and callee.get("type") == "Identifier"
            and callee.get("name") == "eval"
        ):
            self._add_issue(
                code="EVAL_CALL",
                message="Use of eval makes static analysis unreliable.",
                node=callee,
            )
        self._visit(callee, scope)
        self._visit(node.get("arguments", []), scope)

    def _visit_TryStatement(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit(node.get("block"), scope)
        handler = node.get("handler")
        if isinstance(handler, dict):
            self._visit_CatchClause(handler, scope)
        self._visit(node.get("finalizer"), scope)

    def _visit_CatchClause(self, node: Dict[str, Any], scope: Scope) -> None:
        catch_scope = self._new_scope(ScopeType.CATCH, node, scope)
        param = node.get("param")
        if isinstance(param, dict) and param.get("type") == "Identifier":
            catch_scope.add_binding(
                Binding(
                    name=param.get("name"),
                    kind=BindingKind.CATCH_PARAMETER,
                    loc=self._source_position(param),
                    node=param,
                )
            )
        self._visit(node.get("body"), catch_scope)

    def _visit_WithStatement(self, node: Dict[str, Any], scope: Scope) -> None:
        self._add_issue(
            code="WITH_STATEMENT",
            message="`with` statement changes scope resolution dynamically.",
            node=node,
        )
        self._visit(node.get("object"), scope)
        self._visit(node.get("body"), scope)

    def _register_parameter(self, node: Dict[str, Any], scope: Scope) -> None:
        if isinstance(node, dict) and node.get("type") == "Identifier":
            scope.add_binding(
                Binding(
                    name=node.get("name"),
                    kind=BindingKind.PARAMETER,
                    loc=self._source_position(node),
                    node=node,
                )
            )
        else:
            self._add_issue(
                code="UNSUPPORTED_PARAM_PATTERN",
                message="Only simple identifier parameters are supported in ES5 mode.",
                node=node if isinstance(node, dict) else scope.node,
            )


def analyze_bindings(ast: Dict[str, Any], *, source_name: str = "<input>") -> AnalysisResult:
    """
    Run scope and binding analysis on an ES5 AST.

    Args:
        ast: esprima-compatible AST (result of `parse_es5`).
        source_name: Label for diagnostics and reporting.

    Returns:
        AnalysisResult with the scope tree and analysis issues.
    """
    analyzer = _BindingAnalyzer(source_name=source_name)
    return analyzer.analyze(ast)


__all__ = [
    "AnalysisResult",
    "AnalysisIssue",
    "Binding",
    "BindingKind",
    "Scope",
    "ScopeType",
    "analyze_bindings",
]
