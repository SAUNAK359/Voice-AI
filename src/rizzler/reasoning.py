"""Deterministic, bounded reasoning routes; never claim unsupported fact-checking."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

_MATH = re.compile(r"^(?:(?:what is|calculate|compute|evaluate)\s+)?([0-9.()+*/%\-\s]+)\??$", re.I)
_RISK = re.compile(r"\b(?:diagnos(?:e|is)|prescri(?:be|ption)|dosage|investment advice|legal advice|lawsuit|suicid(?:e|al))\b", re.I)
_DEEP = re.compile(r"\b(?:prove|derive|debug|algorithm|architecture|reason|compare|explain why|step.by.step|analyse|analyze|calculate)\b", re.I)


@dataclass(frozen=True)
class Route:
    tier: str
    output_tokens: int
    thinking_level: str
    verified_answer: str | None = None
    verification: str = "not_independently_verified"


def _fraction(node: ast.AST, depth: int = 0) -> Fraction:
    if depth > 12:
        raise ValueError("Expression too deep")
    if isinstance(node, ast.Expression):
        return _fraction(node.body, depth + 1)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        if not -1e12 <= node.value <= 1e12:
            raise ValueError("Number outside safe bounds")
        return Fraction(Decimal(str(node.value)))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        result = _fraction(node.operand, depth + 1)
        return -result if isinstance(node.op, ast.USub) else result
    if isinstance(node, ast.BinOp):
        left, right = _fraction(node.left, depth + 1), _fraction(node.right, depth + 1)
        if isinstance(node.op, ast.Add): value = left + right
        elif isinstance(node.op, ast.Sub): value = left - right
        elif isinstance(node.op, ast.Mult): value = left * right
        elif isinstance(node.op, ast.Div): value = left / right
        elif isinstance(node.op, ast.Pow) and right.denominator == 1 and -8 <= right <= 8:
            value = left ** int(right)
        else: raise ValueError("Unsupported expression")
        if abs(value.numerator) > 10**20 or value.denominator > 10**20:
            raise ValueError("Arithmetic result exceeds bounds")
        return value
    raise ValueError("Unsupported expression")


def verified_arithmetic(text: str) -> str | None:
    """Only accept standalone arithmetic; reject free-form math and Python code."""
    if len(text) > 160:
        return None
    match = _MATH.fullmatch(text.strip().rstrip("?").strip())
    if not match or not any(op in match.group(1) for op in "+-*/"):
        return None
    expr = match.group(1).strip()
    if not expr or not re.fullmatch(r"[0-9.()+*/\-\s]+", expr):
        return None
    try:
        value = _fraction(ast.parse(expr, mode="eval"))
    except (SyntaxError, ArithmeticError, ValueError, OverflowError):
        return None
    if value.denominator == 1:
        return str(value.numerator)
    # Exact fractions never present repeating decimals as if they were exact.
    return f"{value.numerator}/{value.denominator}"


def route(text: str) -> Route:
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        raise ValueError("Invalid prompt")
    exact = verified_arithmetic(text)
    if exact is not None:
        return Route("local", 0, "none", f"The result is {exact}.", "exact_arithmetic")
    if _RISK.search(text):
        return Route("guarded", 650, "high")
    if len(text) > 350 or _DEEP.search(text):
        return Route("deep", 900, "high")
    return Route("fast", 350, "low")
