"""
Scope analysis for JavaScript ASTs (ES5/ES6).

The analyzer walks an esprima-compatible AST, builds a tree of lexical scopes,
and记录`var`、`let`、`const`、函数、类以及 import 等绑定。它同时跟踪可能影响
静态转换的特性（如 `with`、`eval`、解构），为后续翻译阶段提供基础信息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional


class ScopeType(str, Enum):
    GLOBAL = "global"
    FUNCTION = "function"
    BLOCK = "block"
    CLASS = "class"
    CATCH = "catch"


class BindingKind(str, Enum):
    VAR = "var"
    LET = "let"
    CONST = "const"
    FUNCTION = "function"
    CLASS = "class"
    PARAMETER = "parameter"
    CATCH_PARAMETER = "catch_parameter"
    IMPORT = "import"


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

    def _record_binding(
        self, scope: Scope, name: str, kind: BindingKind, node: Dict[str, Any]
    ) -> None:
        if not name:
            return
        binding = Binding(
            name=name,
            kind=kind,
            loc=self._source_position(node),
            node=node,
        )
        scope.add_binding(binding)

    def _resolve_var_scope(self, scope: Scope) -> Scope:
        current = scope
        while current.scope_type not in {ScopeType.GLOBAL, ScopeType.FUNCTION}:
            if current.parent is None:
                break
            current = current.parent
        return current

    def _extract_pattern_identifiers(
        self, pattern: Dict[str, Any], scope: Scope
    ) -> List[Dict[str, Any]]:
        identifiers: List[Dict[str, Any]] = []
        pattern_type = pattern.get("type")
        if pattern_type == "Identifier":
            identifiers.append(pattern)
        elif pattern_type == "AssignmentPattern":
            left = pattern.get("left")
            if isinstance(left, dict):
                identifiers.extend(self._extract_pattern_identifiers(left, scope))
            else:
                self._add_issue(
                    code="UNSUPPORTED_PATTERN",
                    message="Assignment pattern not supported for this identifier.",
                    node=pattern,
                )
        elif pattern_type == "ObjectPattern":
            for prop in pattern.get("properties", []):
                target = prop.get("value") or prop.get("argument")
                if isinstance(target, dict):
                    identifiers.extend(self._extract_pattern_identifiers(target, scope))
        elif pattern_type == "ArrayPattern":
            for element in pattern.get("elements", []):
                if element is None:
                    continue
                if isinstance(element, dict):
                    identifiers.extend(self._extract_pattern_identifiers(element, scope))
        elif pattern_type == "RestElement":
            argument = pattern.get("argument")
            if isinstance(argument, dict):
                identifiers.extend(self._extract_pattern_identifiers(argument, scope))
        else:
            self._add_issue(
                code="UNSUPPORTED_PATTERN",
                message=f"Pattern type '{pattern_type}' is not supported.",
                node=pattern,
            )
        return identifiers

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
        if scope.scope_type == ScopeType.FUNCTION and scope.node.get("body") is node:
            self._visit(node.get("body", []), scope)
            return
        block_scope = self._new_scope(ScopeType.BLOCK, node, scope)
        self._visit(node.get("body", []), block_scope)

    def _visit_VariableDeclaration(self, node: Dict[str, Any], scope: Scope) -> None:
        kind = node.get("kind", "var")
        for declarator in node.get("declarations", []):
            self._visit_VariableDeclarator(declarator, scope, kind)

    def _visit_VariableDeclarator(
        self, node: Dict[str, Any], scope: Scope, declaration_kind: str
    ) -> None:
        identifier = node.get("id")
        target_scope = scope
        binding_kind = BindingKind.VAR
        if declaration_kind == "var":
            target_scope = self._resolve_var_scope(scope)
            binding_kind = BindingKind.VAR
        elif declaration_kind == "let":
            binding_kind = BindingKind.LET
        elif declaration_kind == "const":
            binding_kind = BindingKind.CONST
        else:
            self._add_issue(
                code="UNSUPPORTED_DECLARATION_KIND",
                message=f"Variable declaration kind '{declaration_kind}' is not supported.",
                node=node,
            )

        if isinstance(identifier, dict):
            for simple in self._extract_pattern_identifiers(identifier, scope):
                self._record_binding(target_scope, simple.get("name"), binding_kind, simple)
        # Visit initializer to catch nested functions etc.
        self._visit(node.get("init"), scope)

    def _visit_FunctionDeclaration(self, node: Dict[str, Any], scope: Scope) -> None:
        identifier = node.get("id")
        if isinstance(identifier, dict) and identifier.get("type") == "Identifier":
            self._record_binding(scope, identifier.get("name"), BindingKind.FUNCTION, identifier)
        function_scope = self._new_scope(ScopeType.FUNCTION, node, scope)
        for param in node.get("params", []):
            self._register_parameter(param, function_scope)
        self._visit(node.get("body"), function_scope)

    def _visit_FunctionExpression(self, node: Dict[str, Any], scope: Scope) -> None:
        function_scope = self._new_scope(ScopeType.FUNCTION, node, scope)
        identifier = node.get("id")
        if isinstance(identifier, dict) and identifier.get("type") == "Identifier":
            # Named function expressions bind the name within the inner scope.
            self._record_binding(function_scope, identifier.get("name"), BindingKind.FUNCTION, identifier)
        for param in node.get("params", []):
            self._register_parameter(param, function_scope)
        self._visit(node.get("body"), function_scope)

    def _visit_ArrowFunctionExpression(self, node: Dict[str, Any], scope: Scope) -> None:
        function_scope = self._new_scope(ScopeType.FUNCTION, node, scope)
        for param in node.get("params", []):
            self._register_parameter(param, function_scope)
        body = node.get("body")
        if isinstance(body, dict) and body.get("type") == "BlockStatement":
            self._visit(body, function_scope)
        else:
            self._visit(body, function_scope)

    def _visit_ClassDeclaration(self, node: Dict[str, Any], scope: Scope) -> None:
        identifier = node.get("id")
        if isinstance(identifier, dict) and identifier.get("type") == "Identifier":
            target_scope = scope if scope.scope_type != ScopeType.BLOCK else scope
            self._record_binding(target_scope, identifier.get("name"), BindingKind.CLASS, identifier)
        self._visit_ClassBase(node, scope)

    def _visit_ClassExpression(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit_ClassBase(node, scope)

    def _visit_ClassBase(self, node: Dict[str, Any], scope: Scope) -> None:
        identifier = node.get("id")
        class_scope = self._new_scope(ScopeType.CLASS, node, scope)
        if isinstance(identifier, dict) and identifier.get("type") == "Identifier":
            # Class expressions may have inner binding visible inside class body.
            self._record_binding(class_scope, identifier.get("name"), BindingKind.CLASS, identifier)
        self._visit(node.get("superClass"), scope)
        body = node.get("body", {})
        for element in body.get("body", []):
            self._visit(element, class_scope)

    def _visit_MethodDefinition(self, node: Dict[str, Any], scope: Scope) -> None:
        value = node.get("value")
        self._visit(value, scope)

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
        if not isinstance(node, dict):
            return
        if node.get("type") == "Identifier":
            self._record_binding(scope, node.get("name"), BindingKind.PARAMETER, node)
            return
        if node.get("type") == "RestElement":
            argument = node.get("argument")
            if isinstance(argument, dict):
                self._register_parameter(argument, scope)
            return
        if node.get("type") == "AssignmentPattern":
            self._register_parameter(node.get("left"), scope)
            return
        identifiers = self._extract_pattern_identifiers(node, scope)
        if identifiers:
            for identifier in identifiers:
                self._record_binding(scope, identifier.get("name"), BindingKind.PARAMETER, identifier)
        else:
            self._add_issue(
                code="UNSUPPORTED_PARAM_PATTERN",
                message="Complex parameter pattern not supported.",
                node=node,
            )

    def _visit_ForInStatement(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit(node.get("left"), scope)
        self._visit(node.get("right"), scope)
        self._visit(node.get("body"), scope)

    def _visit_ForOfStatement(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit(node.get("left"), scope)
        self._visit(node.get("right"), scope)
        self._visit(node.get("body"), scope)

    def _visit_TemplateLiteral(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit(node.get("expressions", []), scope)

    def _visit_ImportDeclaration(self, node: Dict[str, Any], scope: Scope) -> None:
        for specifier in node.get("specifiers", []):
            local = specifier.get("local")
            if isinstance(local, dict) and local.get("type") == "Identifier":
                self._record_binding(scope, local.get("name"), BindingKind.IMPORT, local)
        self._visit(node.get("source"), scope)

    def _visit_ExportNamedDeclaration(self, node: Dict[str, Any], scope: Scope) -> None:
        declaration = node.get("declaration")
        if declaration:
            self._visit(declaration, scope)
        for specifier in node.get("specifiers", []):
            exported = specifier.get("exported")
            if isinstance(exported, dict):
                self._visit(exported, scope)

    def _visit_ExportDefaultDeclaration(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit(node.get("declaration"), scope)

    def _visit_ExportAllDeclaration(self, node: Dict[str, Any], scope: Scope) -> None:
        self._visit(node.get("source"), scope)


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
