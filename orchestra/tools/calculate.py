"""Tool calculate: valutare un'espressione aritmetica.

Niente `eval`: e' il vettore classico. Si valuta un AST ristretto ai
numeri e agli operatori, e tutto il resto viene rifiutato.
"""

from __future__ import annotations

from typing import Any

from ..types import Tool


def tool_calculate() -> Tool:
    def handler(expression: str) -> str:
        # valutazione ristretta: solo lettere, numeri e operatori. Niente
        # eval su input del modello — quello è il vettore classico.
        import ast
        import operator as op

        allowed = {
            ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
            ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
            ast.Mod: op.mod, ast.Pow: op.pow, ast.USub: op.neg, ast.UAdd: op.pos,
        }

        def walk(node: Any) -> Any:
            if isinstance(node, ast.Expression):
                return walk(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in allowed:
                return allowed[type(node.op)](walk(node.left), walk(node.right))
            if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
                return allowed[type(node.op)](walk(node.operand))
            raise ValueError(f"espressione non consentita: {type(node).__name__}")

        try:
            return str(walk(ast.parse(expression, mode="eval")))
        except Exception as e:
            return f"ERRORE: {e}"

    return Tool(
        name="calculate",
        description="Calcola un'espressione aritmetica. Supporta + - * / // % **.",
        schema={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Espressione aritmetica, es. '(3+4)*2'"}
            },
            "required": ["expression"],
        },
        handler=handler,
    )
