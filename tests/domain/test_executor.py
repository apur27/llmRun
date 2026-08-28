"""Unit tests for the production `turn_program` DSL executor.

Independent of `tests/test_metric_calibration.py`'s private, test-scoped executor: that module
exists only to freeze the eval tolerance from gold data and is explicitly not production code.
This file drives `src/domain/executor.py`, the real thing, with small hand-picked values whose
expected results are computed here rather than re-asserting numbers pulled from the real
dataset (that gold replay is a later slice).
"""

import pytest

from src.domain.executor import ProgramExecutionError, execute_program


def test_add_sums_two_operands() -> None:
    """`add(a, b)` returns `a + b`."""
    assert execute_program("add(2, 3)") == 5.0


def test_subtract_returns_difference() -> None:
    """`subtract(a, b)` returns `a - b`."""
    assert execute_program("subtract(10, 4)") == 6.0


def test_multiply_returns_product() -> None:
    """`multiply(a, b)` returns `a * b`."""
    assert execute_program("multiply(3, 4)") == 12.0


def test_divide_returns_quotient() -> None:
    """`divide(a, b)` returns `a / b`."""
    assert execute_program("divide(10, 4)") == 2.5


def test_greater_returns_yes_when_first_operand_larger() -> None:
    """`greater(a, b)` returns the string `"yes"` when `a > b`, never a float."""
    result = execute_program("greater(5, 3)")

    assert result == "yes"
    assert isinstance(result, str)


def test_greater_returns_no_when_first_operand_not_larger() -> None:
    """`greater(a, b)` returns the string `"no"` when `a <= b`."""
    assert execute_program("greater(3, 5)") == "no"


def test_bare_literal_program_returns_the_number() -> None:
    """A program with no parentheses is a bare number selection, not a computation."""
    assert execute_program("25.14") == 25.14


def test_chained_back_references_resolve_across_steps() -> None:
    """A later step's `#N` argument resolves to the Nth earlier step's result (0-indexed)."""
    program = "add(1, 2), add(3, 4), add(#0, #1)"

    assert execute_program(program) == 10.0


def test_percentage_argument_divides_by_one_hundred() -> None:
    """A `%`-suffixed argument is divided by 100, not just stripped of the symbol."""
    assert execute_program("add(50%, 0.25)") == pytest.approx(0.75)


def test_const_named_constant_resolves_to_its_magnitude() -> None:
    """`const_X` resolves to `X` as a float."""
    assert execute_program("add(const_100, 1)") == 101.0


def test_const_with_m_prefix_resolves_to_a_negative_value() -> None:
    """`const_mX` resolves to `-X`, the `m` prefix marking a negative constant."""
    assert execute_program("add(const_m1, 5)") == 4.0


def test_bare_literal_with_thousands_comma_strips_the_comma() -> None:
    """A comma thousands separator in a bare-literal program is stripped, not left in the float."""
    assert execute_program("1,234.5") == 1234.5


def test_malformed_program_raises_program_execution_error() -> None:
    """A program step that cannot be parsed raises rather than returning `None` silently."""
    with pytest.raises(ProgramExecutionError):
        execute_program("not_a_valid_step(")


def test_out_of_range_back_reference_raises_program_execution_error() -> None:
    """A `#N` reference to a step that has not run yet raises rather than returning `None`."""
    with pytest.raises(ProgramExecutionError):
        execute_program("add(#0, 1)")


def test_divide_by_zero_raises_program_execution_error() -> None:
    """Dividing by zero raises rather than propagating a raw `ZeroDivisionError`."""
    with pytest.raises(ProgramExecutionError):
        execute_program("divide(5, 0)")
