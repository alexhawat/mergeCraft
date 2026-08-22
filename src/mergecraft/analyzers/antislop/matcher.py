"""Rule matchers for the anti-slop analyzer (#393)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from tree_sitter import Node

    from mergecraft.analyzers.antislop.policy import AntislopRule

_JS_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"})
_PY_SUFFIX = ".py"


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """One anti-slop rule match inside a source file."""

    rule: AntislopRule
    path: str
    start_line: int
    end_line: int
    snippet: str


@dataclass(frozen=True, slots=True)
class _ImportBinding:
    """One imported name plus every spelling that counts as a use of it."""

    name: str
    usage_names: tuple[str, ...]
    line: int


def apply_rules(
    *,
    rel_path: str,
    source: str,
    rules: tuple[AntislopRule, ...],
) -> list[RuleMatch]:
    """Evaluate anti-slop rules against one changed file."""
    language = _language_for_path(rel_path)
    if language is None:
        return []

    matches: list[RuleMatch] = []
    seen: set[tuple[str, int]] = set()
    for rule in rules:
        if language not in rule.languages:
            continue
        for start_line, end_line, snippet in _matches_for_kind(
            rule=rule,
            source=source,
            language=language,
        ):
            key = (rule.rule_id, start_line)
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                RuleMatch(
                    rule=rule,
                    path=rel_path,
                    start_line=start_line,
                    end_line=end_line,
                    snippet=snippet,
                )
            )
    return matches


def _language_for_path(rel_path: str) -> str | None:
    lowered = rel_path.casefold()
    if lowered.endswith(_PY_SUFFIX):
        return "python"
    if any(lowered.endswith(suffix) for suffix in _JS_SUFFIXES):
        if lowered.endswith((".ts", ".tsx")):
            return "typescript"
        return "javascript"
    return None


def _matches_for_kind(
    *,
    rule: AntislopRule,
    source: str,
    language: str,
) -> Iterable[tuple[int, int, str]]:
    kind = rule.match_kind
    if kind == "comment_regex":
        yield from _comment_regex_matches(rule=rule, source=source, language=language)
        return
    if kind == "line_regex":
        yield from _line_regex_matches(rule=rule, source=source)
        return
    if language not in {"python", "javascript", "typescript"}:
        return
    if language != "python":
        if kind == "empty_error_handler":
            yield from _js_empty_error_handler_matches(source=source)
        elif kind == "error_obscuring_catch":
            yield from _js_error_obscuring_catch_matches(source=source)
        return
    if kind == "python_placeholder_implementation":
        yield from _python_placeholder_matches(source=source)
    elif kind == "empty_error_handler":
        yield from _python_empty_error_handler_matches(source=source)
    elif kind == "error_obscuring_catch":
        yield from _python_error_obscuring_catch_matches(source=source)
    elif kind == "python_pass_through_wrapper":
        yield from _python_pass_through_wrapper_matches(source=source)
    elif kind == "python_phantom_import":
        yield from _python_phantom_import_matches(source=source)


def _comment_regex_matches(
    *,
    rule: AntislopRule,
    source: str,
    language: str,
) -> Iterable[tuple[int, int, str]]:
    if not rule.compiled_pattern:
        return
    pattern = rule.compiled_pattern
    prefix = "#" if language == "python" else "//"
    for line_no, line in enumerate(source.splitlines(), start=1):
        comment = _extract_line_comment(line, prefix=prefix)
        if comment is None:
            continue
        if pattern.search(comment):
            yield line_no, line_no, _snippet(comment, pattern)


def _line_regex_matches(
    *,
    rule: AntislopRule,
    source: str,
) -> Iterable[tuple[int, int, str]]:
    if not rule.compiled_pattern:
        return
    pattern = rule.compiled_pattern
    for line_no, line in enumerate(source.splitlines(), start=1):
        search_line = _strip_quoted_literals(line)
        if pattern.search(search_line):
            yield line_no, line_no, _snippet(line, pattern)


def _strip_quoted_literals(line: str) -> str:
    """Drop string literals so regex heuristics do not match prose examples."""
    return re.sub(r"""(['"])(?:\\.|(?!\1).)*\1""", '""', line)


def _extract_line_comment(line: str, *, prefix: str) -> str | None:
    stripped = line.lstrip()
    if not stripped.startswith(prefix):
        return None
    return stripped


def _python_placeholder_matches(source: str) -> Iterable[tuple[int, int, str]]:
    for node, start_line, end_line in _walk_python_functions(source):
        body = _python_function_body(node)
        if body is None:
            continue
        statements = [child for child in body.children if child.type not in {"comment", "\n"}]
        if len(statements) != 1:
            continue
        statement = statements[0]
        if statement.type == "pass_statement":
            yield start_line, end_line, "function body is only pass"
            continue
        if statement.type == "raise_statement":
            text = _node_text(source, statement)
            if "NotImplementedError" in text:
                yield start_line, end_line, text.strip()
            continue
        if statement.type == "expression_statement":
            text = _node_text(source, statement).strip()
            if text == "...":
                yield start_line, end_line, "function body is only ..."


def _except_clause_body(handler: Node) -> Node | None:
    """Return the suite block for an ``except_clause`` node.

    tree-sitter-python exposes the suite as an unnamed ``block`` child, not a
    named ``body`` field.
    """
    blocks = _child_nodes(handler, "block")
    return blocks[0] if blocks else None


def _python_empty_error_handler_matches(source: str) -> Iterable[tuple[int, int, str]]:
    for _node, _start_line, end_line in _walk_python_try_blocks(source):
        for handler in _child_nodes(_node, "except_clause"):
            block = _except_clause_body(handler)
            if block is None:
                continue
            statements = [child for child in block.children if child.type not in {"comment", "\n"}]
            if len(statements) == 1 and statements[0].type == "pass_statement":
                line = handler.start_point[0] + 1
                yield line, end_line, "except block only passes"


def _python_error_obscuring_catch_matches(source: str) -> Iterable[tuple[int, int, str]]:
    for _node, _start_line, end_line in _walk_python_try_blocks(source):
        for handler in _child_nodes(_node, "except_clause"):
            block = _except_clause_body(handler)
            if block is None:
                continue
            statements = [child for child in block.children if child.type not in {"comment", "\n"}]
            if len(statements) != 1 or statements[0].type != "return_statement":
                continue
            text = _node_text(source, statements[0]).strip()
            if re.fullmatch(r"return\s+None\b.*", text):
                line = handler.start_point[0] + 1
                yield line, end_line, text


def _python_pass_through_wrapper_matches(source: str) -> Iterable[tuple[int, int, str]]:
    for node, start_line, end_line in _walk_python_functions(source):
        params = _python_parameter_names(node)
        if not params:
            continue
        body = _python_function_body(node)
        if body is None:
            continue
        statements = [child for child in body.children if child.type not in {"comment", "\n"}]
        if len(statements) != 1 or statements[0].type != "return_statement":
            continue
        call = _return_call_expression(statements[0])
        if call is None:
            continue
        callee = call.child_by_field_name("function")
        if callee is None:
            continue
        forwarded = _call_positional_argument_names(call)
        if forwarded != params:
            continue
        callee_name = _node_text(source, callee).strip()
        func_name = _python_function_name(node)
        if func_name is None or callee_name == func_name:
            continue
        yield start_line, end_line, _node_text(source, statements[0]).strip()


def _python_phantom_import_matches(source: str) -> Iterable[tuple[int, int, str]]:
    bindings: list[_ImportBinding] = []
    for node in _walk_python_nodes(source):
        if node.type == "import_statement":
            line_no = node.start_point[0] + 1
            for child in node.children:
                if child.type == "dotted_name":
                    root = _node_text(source, child).split(".", 1)[0]
                    bindings.append(_ImportBinding(name=root, usage_names=(root,), line=line_no))
                elif child.type == "aliased_import":
                    binding = _aliased_module_binding(source, child, line_no=line_no)
                    if binding is not None:
                        bindings.append(binding)
        elif node.type == "import_from_statement":
            seen_import_keyword = False
            for child in node.children:
                if child.type == "import":
                    seen_import_keyword = True
                    continue
                if not seen_import_keyword:
                    continue
                if child.type == "aliased_import":
                    alias = child.child_by_field_name("alias")
                    name_node = child.child_by_field_name("name")
                    line_no = node.start_point[0] + 1
                    if alias is not None:
                        bound = _node_text(source, alias)
                        bindings.append(
                            _ImportBinding(name=bound, usage_names=(bound,), line=line_no)
                        )
                    elif name_node is not None:
                        bound = _node_text(source, name_node)
                        bindings.append(
                            _ImportBinding(name=bound, usage_names=(bound,), line=line_no)
                        )
                elif child.type in {"dotted_name", "identifier"}:
                    bound = _node_text(source, child)
                    bindings.append(
                        _ImportBinding(
                            name=bound,
                            usage_names=(bound,),
                            line=child.start_point[0] + 1,
                        )
                    )

    if not bindings:
        return

    type_checking_only = _type_checking_only_imports(source)
    body_without_imports = _strip_python_imports(source)
    for binding in bindings:
        if any(name in type_checking_only for name in binding.usage_names):
            continue
        if any(
            re.search(rf"\b{re.escape(name)}\b", body_without_imports)
            for name in binding.usage_names
        ):
            continue
        yield binding.line, binding.line, f"import {binding.name} is unused"


def _aliased_module_binding(source: str, node: Node, *, line_no: int) -> _ImportBinding | None:
    """Build the binding for ``import x.y as z``.

    ``import x.y as z`` binds ``z`` and nothing else — the module name is not
    in scope afterwards, so ``x.y.thing()`` would raise ``NameError``. The
    alias is therefore the only spelling that can count as a use; treating the
    module root as one too would suppress a genuinely dead import whenever the
    body happens to mention it in a docstring or comment. Without an alias the
    plain ``import x.y`` form binds the root instead.
    """
    name_node = node.child_by_field_name("name")
    alias_node = node.child_by_field_name("alias")
    if alias_node is not None:
        alias = _node_text(source, alias_node)
        return _ImportBinding(name=alias, usage_names=(alias,), line=line_no)
    if name_node is None:
        return None
    root = _node_text(source, name_node).split(".", 1)[0]
    return _ImportBinding(name=root, usage_names=(root,), line=line_no)


def _js_empty_error_handler_matches(*, source: str) -> Iterable[tuple[int, int, str]]:
    patterns = (
        re.compile(r"catch\s*\{\s*\}", re.DOTALL),
        re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}", re.DOTALL),
        re.compile(r"catch\s*\([^)]*\)\s*\{\s*/\*[^*]*\*/\s*\}", re.DOTALL),
    )
    for pattern in patterns:
        for match in pattern.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            yield line, line, match.group(0).strip()


def _js_error_obscuring_catch_matches(*, source: str) -> Iterable[tuple[int, int, str]]:
    pattern = re.compile(
        r"catch\s*(?:\([^)]*\))?\s*\{[^}]*\breturn\s+(?:null|undefined)\b",
        re.DOTALL,
    )
    for match in pattern.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        yield line, line, match.group(0).strip()


def _type_checking_only_imports(source: str) -> frozenset[str]:
    """Names imported only under ``if TYPE_CHECKING:`` blocks."""
    names: set[str] = set()
    for node in _walk_python_nodes(source):
        if node.type != "if_statement":
            continue
        condition = node.child_by_field_name("condition")
        if condition is None or "TYPE_CHECKING" not in _node_text(source, condition):
            continue
        consequence = node.child_by_field_name("consequence")
        if consequence is None:
            continue
        for child in consequence.children:
            names.update(_collect_import_names(source, child))
    return frozenset(names)


def _collect_import_names(source: str, node: Node) -> set[str]:
    collected: set[str] = set()
    if node.type == "import_statement":
        for child in node.children:
            if child.type == "dotted_name":
                collected.add(_node_text(source, child).split(".", 1)[0])
            elif child.type == "aliased_import":
                # Mirror `_aliased_module_binding`: `import x.y as z` binds `z`
                # alone. This set suppresses phantom-import findings, so adding
                # the module root as well would silence a real one.
                alias_node = child.child_by_field_name("alias")
                if alias_node is not None:
                    collected.add(_node_text(source, alias_node))
                    continue
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    collected.add(_node_text(source, name_node).split(".", 1)[0])
    elif node.type == "import_from_statement":
        seen_import_keyword = False
        for child in node.children:
            if child.type == "import":
                seen_import_keyword = True
                continue
            if not seen_import_keyword:
                continue
            if child.type == "aliased_import":
                alias = child.child_by_field_name("alias")
                name_node = child.child_by_field_name("name")
                if alias is not None:
                    collected.add(_node_text(source, alias))
                elif name_node is not None:
                    collected.add(_node_text(source, name_node))
            elif child.type in {"dotted_name", "identifier"}:
                collected.add(_node_text(source, child))
    elif node.type == "block":
        for child in node.children:
            collected.update(_collect_import_names(source, child))
    return collected


def _walk_python_functions(source: str) -> Iterable[tuple[Node, int, int]]:
    for node in _walk_python_nodes(source):
        if node.type != "function_definition":
            continue
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        yield node, start_line, end_line


def _walk_python_try_blocks(source: str) -> Iterable[tuple[Node, int, int]]:
    for node in _walk_python_nodes(source):
        if node.type != "try_statement":
            continue
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        yield node, start_line, end_line


def _walk_python_nodes(source: str) -> Iterable[Node]:
    root = _parse_python_root(source)

    def walk(node: Node) -> Iterable[Node]:
        yield node
        for child in node.children:
            yield from walk(child)

    yield from walk(root)


@lru_cache(maxsize=32)
def _parse_python_root(source: str) -> Node:
    import tree_sitter_python as tspython
    from tree_sitter import Language, Parser

    parser = Parser(Language(tspython.language()))
    tree = parser.parse(source.encode("utf-8"))
    return tree.root_node


def _python_function_body(node: Node) -> Node | None:
    return node.child_by_field_name("body")


def _python_function_name(node: Node) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _node_text_from_node(name_node)


def _python_parameter_names(node: Node) -> tuple[str, ...]:
    params_node = node.child_by_field_name("parameters")
    if params_node is None:
        return ()
    names: list[str] = []
    for child in params_node.children:
        if child.type == "identifier":
            names.append(_node_text_from_node(child))
        elif child.type in {"typed_parameter", "default_parameter", "typed_default_parameter"}:
            name_node = child.child_by_field_name("name")
            if name_node is None:
                for grandchild in child.children:
                    if grandchild.type == "identifier":
                        name_node = grandchild
                        break
            if name_node is not None:
                names.append(_node_text_from_node(name_node))
    return tuple(names)


def _return_call_expression(return_node: Node) -> Node | None:
    for child in return_node.children:
        if child.type == "call":
            return child
    return None


def _call_positional_argument_names(call_node: Node) -> tuple[str, ...]:
    names: list[str] = []
    args = call_node.child_by_field_name("arguments")
    if args is None:
        return ()
    for child in args.children:
        if child.type in {"identifier", "attribute"}:
            names.append(_node_text_from_node(child))
        elif child.type == "keyword_argument":
            return ()
    return tuple(names)


def _child_nodes(node: Node, node_type: str) -> list[Node]:
    return [child for child in node.children if child.type == node_type]


def _node_text(source: str, node: Node) -> str:
    return _node_text_from_node(node)


def _node_text_from_node(node: Node) -> str:
    text = getattr(node, "text", b"")
    if isinstance(text, bytes):
        return text.decode("utf-8")
    return str(text)


def _strip_python_imports(source: str) -> str:
    lines: list[str] = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("import ", "from ")):
            continue
        lines.append(line)
    return "\n".join(lines)


def _snippet(text: str, pattern: re.Pattern[str], *, limit: int = 120) -> str:
    match = pattern.search(text)
    if match is None:
        cleaned = " ".join(text.split())
        return cleaned[:limit]
    start = max(match.start() - 20, 0)
    end = min(match.end() + 20, len(text))
    cleaned = " ".join(text[start:end].split())
    return cleaned[:limit]


__all__ = ["RuleMatch", "apply_rules"]
