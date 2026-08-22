"""Rule matchers for the anti-slop analyzer (#393)."""

from __future__ import annotations

import re
from dataclasses import dataclass
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
            rel_path=rel_path,
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
    rel_path: str,
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
    if not rule.pattern:
        return
    pattern = re.compile(rule.pattern)
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
    if not rule.pattern:
        return
    pattern = re.compile(rule.pattern)
    for line_no, line in enumerate(source.splitlines(), start=1):
        if pattern.search(line):
            yield line_no, line_no, _snippet(line, pattern)


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


def _python_empty_error_handler_matches(source: str) -> Iterable[tuple[int, int, str]]:
    for _node, _start_line, end_line in _walk_python_try_blocks(source):
        for handler in _child_nodes(_node, "except_clause"):
            block = handler.child_by_field_name("body")
            if block is None:
                continue
            statements = [child for child in block.children if child.type not in {"comment", "\n"}]
            if len(statements) == 1 and statements[0].type == "pass_statement":
                line = handler.start_point[0] + 1
                yield line, end_line, "except block only passes"


def _python_error_obscuring_catch_matches(source: str) -> Iterable[tuple[int, int, str]]:
    for _node, _start_line, end_line in _walk_python_try_blocks(source):
        for handler in _child_nodes(_node, "except_clause"):
            block = handler.child_by_field_name("body")
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
    import_names: list[tuple[str, int]] = []
    for node in _walk_python_nodes(source):
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    import_names.append(
                        (_node_text(source, child).split(".", 1)[0], node.start_point[0] + 1)
                    )
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    if name_node is not None:
                        import_names.append(
                            (
                                _node_text(source, name_node).split(".", 1)[0],
                                node.start_point[0] + 1,
                            )
                        )
        elif node.type == "import_from_statement":
            for child in node.children:
                if child.type in {"dotted_name", "identifier"}:
                    import_names.append((_node_text(source, child), node.start_point[0] + 1))
                elif child.type == "aliased_import":
                    alias = child.child_by_field_name("alias")
                    name_node = child.child_by_field_name("name")
                    if alias is not None:
                        import_names.append((_node_text(source, alias), node.start_point[0] + 1))
                    elif name_node is not None:
                        import_names.append(
                            (_node_text(source, name_node), node.start_point[0] + 1)
                        )

    if not import_names:
        return

    body_without_imports = _strip_python_imports(source)
    for name, line_no in import_names:
        if re.search(rf"\b{re.escape(name)}\b", body_without_imports):
            continue
        yield line_no, line_no, f"import {name} is unused"


def _js_empty_error_handler_matches(*, source: str) -> Iterable[tuple[int, int, str]]:
    pattern = re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}")
    for match in pattern.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        yield line, line, match.group(0).strip()


def _js_error_obscuring_catch_matches(*, source: str) -> Iterable[tuple[int, int, str]]:
    pattern = re.compile(r"catch\s*\([^)]*\)\s*\{[^}]*\breturn\s+null\b")
    for match in pattern.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        yield line, line, match.group(0).strip()


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
    import tree_sitter_python as tspython
    from tree_sitter import Language, Parser

    parser = Parser(Language(tspython.language()))
    tree = parser.parse(source.encode("utf-8"))

    def walk(node: Node) -> Iterable[Node]:
        yield node
        for child in node.children:
            yield from walk(child)

    yield from walk(tree.root_node)


def _python_function_body(node: Node) -> Node | None:
    body = node.child_by_field_name("body")
    if body is None:
        return None
    if body.type == "block":
        return body
    return body


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
    start = node.start_byte
    end = node.end_byte
    return source[start:end]


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
