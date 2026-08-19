"""Deterministic executor for the ConvFinQA `turn_program` DSL.

Arithmetic never happens in-token: a model selects numbers and names an operation, this module
computes the result. Pure: no I/O, no SDK, no network, no clock. Handles only the *within-turn*
`#N` back-reference system (a program step referencing an earlier step's result in the same
program string) — cross-turn conversation state is a distinct reference system and is a later
module's job, not this one's.

Six operations appear in the dataset: `add`, `subtract`, `multiply`, `divide`, `greater`
(returns `"yes"`/`"no"`, never a float), and the implicit `literal` case for a bare-number
program with no operation at all.
"""

import re

_STEP_PATTERN = re.compile(r"^(?P<op>\w+)\((?P<args>.*)\)$")
_LITERAL_OP = "literal"
_BACK_REFERENCE_PREFIX = "#"
_CONST_PREFIX = "const_"
_NEGATIVE_CONST_MARKER = "m"
_PERCENT_SUFFIX = "%"
_PERCENT_DIVISOR = 100.0


class ProgramExecutionError(Exception):
    """Raised when a `turn_program` string cannot be parsed or an argument cannot be resolved.

    PROPAGATES: no handler exists in this slice. A malformed program at this layer is a bug
    upstream (a wrong DSL string reaching the executor), not a valid runtime state to swallow,
    so this is intended to propagate to the top level and terminate the process until a later
    eval-runner service module catches it and records a `parse_error` outcome instead.
    """


def execute_program(program: str) -> float | str:
    """Execute a `turn_program` DSL string and return its final result.

    A bare literal (no parentheses) returns that number directly. Otherwise the program is one
    or more comma-separated operation steps, each usable by later steps via `#N` back-references
    to the Nth step's result (0-indexed). Raises `ProgramExecutionError` if the program cannot
    be parsed or any argument cannot be resolved; never returns `None`.
    """
    results: list[float | str] = []
    for op, args in _tokenize(program):
        if op == _LITERAL_OP:
            results.append(_resolve_arg(args[0], results))
            continue
        first = _resolve_arg(args[0], results)
        second = _resolve_arg(args[1], results)
        results.append(_apply_operation(op, first, second))
    return results[-1]


def _tokenize(program: str) -> list[tuple[str, list[str]]]:
    """Split a program string into its `(op, args)` steps, or a single literal step."""
    if "(" not in program:
        return [(_LITERAL_OP, [program.strip()])]

    steps = []
    for part in program.split("), "):
        part = part.strip()
        if not part.endswith(")"):
            part += ")"
        match = _STEP_PATTERN.match(part)
        if match is None:
            raise ProgramExecutionError(f"malformed program step: {part!r}")
        op = match.group("op")
        args = [a.strip() for a in match.group("args").split(",")]
        steps.append((op, args))
    return steps


def _apply_operation(op: str, first: float, second: float) -> float | str:
    """Apply one of the six DSL operations to two already-resolved operands."""
    if op == "add":
        return first + second
    if op == "subtract":
        return first - second
    if op == "multiply":
        return first * second
    if op == "divide":
        if second == 0:
            raise ProgramExecutionError(f"division by zero: {first!r} / {second!r}")
        return first / second
    if op == "greater":
        return "yes" if first > second else "no"
    raise ProgramExecutionError(f"unknown operation: {op!r}")


def _resolve_arg(arg: str, results: list[float | str]) -> float:
    """Resolve one DSL argument to a float: a back-reference, a `const_`, or a numeric literal."""
    if arg.startswith(_BACK_REFERENCE_PREFIX):
        return _resolve_back_reference(arg, results)
    if arg.startswith(_CONST_PREFIX):
        return _resolve_const(arg)
    return _resolve_numeric_literal(arg)


def _resolve_back_reference(arg: str, results: list[float | str]) -> float:
    """Resolve a `#N` argument to the Nth earlier step's result, which must be numeric."""
    index_text = arg[len(_BACK_REFERENCE_PREFIX) :]
    try:
        index = int(index_text)
    except ValueError as exc:
        raise ProgramExecutionError(f"malformed back-reference: {arg!r}") from exc
    if index < 0 or index >= len(results):
        raise ProgramExecutionError(f"back-reference out of range: {arg!r}")
    referenced = results[index]
    if not isinstance(referenced, float):
        raise ProgramExecutionError(
            f"back-reference {arg!r} resolves to a non-numeric value: {referenced!r}"
        )
    return referenced


def _resolve_const(arg: str) -> float:
    """Resolve a `const_X` argument, where `X` is a number optionally prefixed with `m`."""
    remainder = arg[len(_CONST_PREFIX) :]
    is_negative = remainder.startswith(_NEGATIVE_CONST_MARKER)
    magnitude_text = (
        remainder[len(_NEGATIVE_CONST_MARKER) :] if is_negative else remainder
    )
    try:
        magnitude = float(magnitude_text)
    except ValueError as exc:
        raise ProgramExecutionError(f"malformed constant: {arg!r}") from exc
    return -magnitude if is_negative else magnitude


def _resolve_numeric_literal(arg: str) -> float:
    """Resolve a plain or percentage numeric literal, stripping thousands commas."""
    is_percentage = arg.endswith(_PERCENT_SUFFIX)
    text = arg[: -len(_PERCENT_SUFFIX)] if is_percentage else arg
    text = text.replace(",", "")
    try:
        value = float(text)
    except ValueError as exc:
        raise ProgramExecutionError(f"cannot resolve argument: {arg!r}") from exc
    return value / _PERCENT_DIVISOR if is_percentage else value
