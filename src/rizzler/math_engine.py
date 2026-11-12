"""Bounded symbolic mathematics: parse a small untrusted equation grammar, solve, verify.

SymPy is an optional dedicated dependency. The parser never evals model text;
unsupported/ambiguous speech declines instead of inventing solutions.
"""
from __future__ import annotations

import ast
import re


SYMBOLS = "abcxyz"
_NUMBERS = {"zero":"0","one":"1","two":"2","three":"3","four":"4",
            "five":"5","six":"6","seven":"7","eight":"8","nine":"9","ten":"10"}
_SOURCE = re.compile(r"\b(?:root\s+under|square\s+root\s+of)\s+(\d+)\b", re.I)
_TRIGGER = re.compile(r"\b(?:solve|equation|value of [abxyz]|[abxyz] (?:squared|square)|sqrt\s*\(|root under)\b", re.I)


def equation_text(text: str) -> tuple[list[str], list[str]] | None:
    """Convert clearly stated two-variable equations; never guess missing operators."""
    if not isinstance(text, str) or len(text) > 850 or not _TRIGGER.search(text):
        return None
    s = text.lower().replace("√", "sqrt").replace("²", "^2").replace("−","-")
    for word, digit in _NUMBERS.items():
        s = re.sub(r"\b" + word + r"\b", digit, s)
    s = re.split(r"\b(?:consider even|even if|i want you|give me|represent imaginary|what is the value)\b", s, maxsplit=1)[0]
    s = _SOURCE.sub(r"sqrt(\1)", s)
    s = re.sub(r"\b([abxyz])\s+(?:squared|square)\b", r"\1^2", s)
    s = re.sub(r"\b(?:is equal to|equals|equal to|equal)\b", "=", s)
    s = re.sub(r"\bplus\b", "+", s)
    s = re.sub(r"\bminus\b", "-", s)
    s = re.sub(r"\b(?:multiplied by|times)\b", "*", s)
    s = re.sub(r"\b(?:divided by|over|by)\b", "/", s)
    s = re.sub(r"\b(?:first problem is|the problem is|if|then|so|okay|help me|please|find|solve|equations?|value|of|a|the|are|is|to|for|and)\b", lambda m: m.group(0) if m.group(0) in ("a","and") else " ", s)
    # Restore equation operands; 'and' is a separator, never executable syntax.
    parts = re.split(r"\s+and\s+", s)
    eqns = []
    for part in parts:
        part = part.strip(" .,;:?!")
        if "=" not in part:
            continue
        start = re.search(r"(?:sqrt\s*\(|[abxyz](?=\W|$)|\d+(?=\W|$))", part)
        if start:
            part = part[start.start():]
        if part.count("=") != 1 or len(part) > 180:
            return None
        left,right = (v.strip().replace("^","**") for v in part.split("="))
        if not left or not right:
            return None
        eqns.append((left,right))
    variables = sorted(set(re.findall(r"\b[abxyz]\b", " ".join(l+" "+r for l,r in eqns))))
    if len(eqns) != 2 or len(variables) != 2:
        return None
    return [l+"="+r for l,r in eqns], variables


def _expression(source: str, symbol_map, sp):
    """Untrusted expression AST -> vetted SymPy operations, no eval/parse_expr."""
    if not re.fullmatch(r"[0-9a-zA-Z_().+*/ -]{1,180}", source):
        raise ValueError("Invalid mathematical expression")
    node = ast.parse(source, mode="eval")
    count = [0]
    def walk(part, depth=0):
        count[0] += 1
        if depth > 15 or count[0] > 80:
            raise ValueError("Expression too complex")
        if isinstance(part, ast.Expression):
            return walk(part.body, depth+1)
        if isinstance(part, ast.Constant) and type(part.value) is int and 0 <= part.value <= 10000:
            return sp.Integer(part.value)
        if isinstance(part, ast.Name) and part.id in symbol_map:
            return symbol_map[part.id]
        if isinstance(part, ast.UnaryOp) and isinstance(part.op,(ast.USub,ast.UAdd)):
            v=walk(part.operand,depth+1)
            return -v if isinstance(part.op,ast.USub) else v
        if isinstance(part,ast.Call) and isinstance(part.func,ast.Name) and part.func.id=="sqrt" and len(part.args)==1 and not part.keywords:
            v=walk(part.args[0],depth+1)
            if not v.is_number or v.is_negative or v>10000:
                raise ValueError("Square root argument unsupported")
            return sp.sqrt(v)
        if isinstance(part,ast.BinOp):
            a,b=walk(part.left,depth+1),walk(part.right,depth+1)
            if isinstance(part.op,ast.Add):return a+b
            if isinstance(part.op,ast.Sub):return a-b
            if isinstance(part.op,ast.Mult):return a*b
            if isinstance(part.op,ast.Div):
                if b==0:raise ValueError("Division by zero")
                return a/b
            if isinstance(part.op,ast.Pow) and b.is_Integer and 0<=b<=4:
                return a**b
        raise ValueError("Unsupported equation operation")
    return walk(node)


def _complex_number(value, sp):
    z=complex(sp.N(value, 13))
    def clean(v):
        return 0.0 if abs(v)<1e-9 else float(v)
    return complex(clean(z.real),clean(z.imag))


def _format_num(z:complex) -> str:
    a,b=z.real,z.imag
    if abs(b)<1e-8:return f"{a:.6f}"
    sign="+" if b>=0 else "-"
    if abs(a)<1e-8:return f"{'-' if b<0 else ''}{abs(b):.6f}i"
    return f"{a:.6f}{sign}{abs(b):.6f}i"


def solve_equations(text: str) -> dict | None:
    """Solve supported 2x2 symbolic systems and substitute into original equations."""
    parsed=equation_text(text)
    if not parsed:return None
    equations,names=parsed
    import sympy as sp
    symbols={name:sp.Symbol(name) for name in names}
    pairs=[]
    for item in equations:
        left,right=item.split("=",1)
        lhs,rhs=_expression(left,symbols,sp),_expression(right,symbols,sp)
        pairs.append((lhs,rhs))
    polys=[]
    for lhs,rhs in pairs:
        numerator,denominator=sp.fraction(sp.together(lhs-rhs))
        poly=sp.Poly(numerator,*symbols.values())
        if poly.total_degree()>4 or len(poly.terms())>30:
            raise ValueError("Equation exceeds bounded polynomial policy")
        polys.append(poly.as_expr())
    candidate=sp.solve(polys,list(symbols.values()),dict=True,simplify=False)
    if not candidate or len(candidate)>12:
        raise ValueError("No bounded solution set found")
    results=[]
    for row in candidate:
        if any(name not in row for name in symbols.values()):
            continue
        subs={x:row[x] for x in symbols.values()}
        if any(abs(complex(sp.N((lhs-rhs).subs(subs),12)))>1e-6 for lhs,rhs in pairs):
            continue
        vals={name:_complex_number(row[sym],sp) for name,sym in symbols.items()}
        if not all(abs(v.real)<1e8 and abs(v.imag)<1e8 for v in vals.values()):
            continue
        if vals not in results:results.append(vals)
    if not results:
        raise ValueError("Candidate solutions did not verify")
    results.sort(key=lambda x:(-x[names[0]].real,x[names[0]].imag))
    lines=["**Verified solutions**", "", "| Solution | "+ " | ".join(names)+" |",
           "| --- | "+" | ".join("---" for _ in names)+" |"]
    for i,row in enumerate(results,1):
        lines.append("| "+str(i)+" | "+" | ".join("\\("+name+"="+_format_num(row[name])+"\\)" for name in names)+" |")
    lines+=["", "Each pair was checked against the original equations. Values are rounded to six decimal places."]
    spoken="I found "+str(len(results))+" verified solution pairs. "
    for i,row in enumerate(results,1):
        spoken+="Solution "+str(i)+": "+", ".join(name+" equals "+_format_num(row[name]).replace("i"," times i") for name in names)+". "
    return {"text":"\n".join(lines),"spoken":spoken,
            "solutions":[{name:_format_num(row[name]) for name in names} for row in results],
            "equations":equations,"verification":"symbolic_substitution"}
