"""Tool analisi_python: la struttura del codice, senza leggere il file.

PERCHE' ESISTE

Per rispondere a "dove e' definita questa funzione" l'agente aveva due
strade: `search_text` (che trova il nome ma non dice se e' una
definizione, una chiamata o una stringa) e `read_file` (che costa token
e riempie il contesto di righe che non servono). L'albero sintattico
risponde alla domanda vera — quali simboli, a che riga, chi chiama chi —
senza leggere il corpo.

COSA NON E'

Non e' un type checker e non e' un linter: non dice se il codice e'
giusto. L'unica cosa che dice sulla correttezza e' se il file compila
(`sintassi`), che e' comunque il primo errore da escludere.
Riguarda solo Python: per JavaScript l'albero non c'e' e il tool lo
dice, invece di restituire un risultato vuoto che sembra "niente
definizioni".
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..types import Tool
from ._guard import _motivo_sensibile, _safe_path

_MAX_SIMBOLI = 400
_MAX_RIGHE = 300


def _firma(node: ast.AST) -> str:
    """La firma come la scriveresti, senza il corpo."""
    try:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ast.unparse(node.args) if hasattr(ast, "unparse") else ""
            ritorno = ""
            if getattr(node, "returns", None) is not None \
                    and hasattr(ast, "unparse"):
                ritorno = " -> " + ast.unparse(node.returns)
            prefisso = "async def" if isinstance(node, ast.AsyncFunctionDef) \
                else "def"
            return f"{prefisso} {node.name}({args}){ritorno}"
        if isinstance(node, ast.ClassDef):
            basi = ", ".join(ast.unparse(b) for b in node.bases
                             if hasattr(ast, "unparse"))
            return f"class {node.name}" + (f"({basi})" if basi else "")
    except Exception:  # noqa: BLE001
        pass
    return getattr(node, "name", "?")


def _simboli(tree: ast.AST) -> list[str]:
    """Definizioni con riga, annidamento e firma."""
    righe: list[str] = []

    def cammina(nodi, dentro: str = "") -> None:
        for node in nodi:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                if len(righe) >= _MAX_SIMBOLI:
                    return
                tipo = "classe" if isinstance(node, ast.ClassDef) else "funzione"
                dove = f" [in {dentro}]" if dentro else ""
                righe.append(f"{node.lineno}: {tipo} {_firma(node)}{dove}")
                # Le funzioni annidate contano: sono il punto in cui una
                # ricerca per nome trova un simbolo che non e' visibile
                # fuori, e il modello deve saperlo.
                cammina(node.body, dentro=node.name if dentro == ""
                        else f"{dentro}.{node.name}")
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For,
                                   ast.While)):
                for campo in ("body", "orelse", "finalbody", "handlers"):
                    sotto = getattr(node, campo, None)
                    if isinstance(sotto, list):
                        cammina(sotto, dentro)

    cammina(tree.body)
    return righe


def _import(tree: ast.AST) -> list[str]:
    righe: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                righe.append(f"{node.lineno}: import {a.name}"
                             + (f" as {a.asname}" if a.asname else ""))
        elif isinstance(node, ast.ImportFrom):
            modulo = node.module or ""
            if node.level:
                modulo = "." * node.level + modulo
            nomi = ", ".join(a.name + (f" as {a.asname}" if a.asname else "")
                             for a in node.names)
            righe.append(f"{node.lineno}: from {modulo} import {nomi}")
    return sorted(righe, key=lambda s: int(s.split(":", 1)[0]))


def _chiamate(tree: ast.AST, filtro: str) -> list[str]:
    """Le chiamate, con la funzione che le contiene.

    Il contenitore e' la parte che rende utile il risultato: "riga 42:
    open(...)" senza sapere in che funzione sta non dice chi lo fa.
    """
    righe: list[str] = []

    class Visitatore(ast.NodeVisitor):
        def __init__(self) -> None:
            self.pila: list[str] = []

        def visit_FunctionDef(self, node):  # noqa: N802
            self.pila.append(node.name)
            self.generic_visit(node)
            self.pila.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815

        def visit_ClassDef(self, node):  # noqa: N802
            self.pila.append(node.name)
            self.generic_visit(node)
            self.pila.pop()

        def visit_Call(self, node: ast.Call):  # noqa: N802
            try:
                nome = ast.unparse(node.func)
            except Exception:  # noqa: BLE001
                nome = "?"
            if filtro and filtro not in nome:
                self.generic_visit(node)
                return
            if len(righe) < _MAX_RIGHE:
                dentro = ".".join(self.pila) or "<modulo>"
                righe.append(f"{node.lineno}: {nome}(...)  in {dentro}")
            self.generic_visit(node)

    Visitatore().visit(tree)
    return righe


def _usi(tree: ast.AST, nome: str) -> list[str]:
    """Dove un nome viene letto o scritto, con la funzione che lo contiene."""
    righe: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == nome:
            righe.append(f"{node.lineno}: {nome}")
        elif isinstance(node, ast.Attribute) and node.attr == nome:
            righe.append(f"{node.lineno}: .{nome}")
    return sorted(righe, key=lambda s: int(s.split(":", 1)[0]))


def tool_analisi_python() -> Tool:
    """Legge la struttura di un file Python: simboli, import, chiamate."""

    def handler(path: str = "", cosa: str = "simboli",
                nome: str = "") -> str:
        if not (path or "").strip():
            return "Quale file? Serve un percorso (es. orchestra/agent.py)."
        try:
            p: Path = _safe_path(path)
        except (ValueError, PermissionError) as e:
            return f"ERRORE: {e}"
        if not p.is_file():
            return f"NON ESISTE: {path}"
        motivo = _motivo_sensibile(p)
        if motivo:
            return f"NON LETTO: {motivo}."
        if p.suffix.lower() not in (".py", ".pyw"):
            return (f"FORMATO NON SUPPORTATO: {p.name}. analisi_python "
                    f"lavora sull'albero sintattico Python (.py). Per altri "
                    f"linguaggi usa search_text o read_file.")
        try:
            testo = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"ERRORE di lettura: {e}"
        try:
            tree = ast.parse(testo, filename=str(p))
        except SyntaxError as e:
            return (f"ERRORE DI SINTASSI in {path}:{e.lineno} "
                    f"(colonna {e.offset}): {e.msg}\n"
                    f"  {(e.text or '').rstrip()}\n"
                    f"Il file non compila: nessun altro dato e' affidabile "
                    f"finche' questo non e' corretto.")
        cosa = (cosa or "simboli").strip().lower()
        if cosa in ("sintassi", "syntax"):
            return f"{path}: sintassi valida ({len(testo.splitlines())} righe)."
        if cosa in ("simboli", "symbols", "definizioni"):
            righe = _simboli(tree)
            if not righe:
                return f"{path}: nessuna funzione o classe definita."
            return (f"{path}: {len(righe)} definizioni\n" + "\n".join(righe))
        if cosa in ("import", "imports"):
            righe = _import(tree)
            return (f"{path}: {len(righe)} import\n" + "\n".join(righe)
                    if righe else f"{path}: nessun import.")
        if cosa in ("chiamate", "calls"):
            righe = _chiamate(tree, (nome or "").strip())
            if not righe:
                return (f"{path}: nessuna chiamata"
                        + (f" a {nome}" if nome else "") + ".")
            testa = f"{path}: {len(righe)} chiamate"
            if len(righe) >= _MAX_RIGHE:
                testa += f" (fermo a {_MAX_RIGHE}: restringi con `nome`)"
            return testa + "\n" + "\n".join(righe)
        if cosa in ("usi", "riferimenti", "refs"):
            if not (nome or "").strip():
                return "Per `usi` serve `nome`: quale simbolo cerco?"
            righe = _usi(tree, nome.strip())
            if not righe:
                return f"{path}: {nome} non compare."
            return f"{path}: {len(righe)} usi di {nome}\n" + "\n".join(righe)
        return (f"COSA NON RICONOSCIUTA: {cosa}. Valori: simboli, import, "
                f"chiamate, usi, sintassi.")

    return Tool(
        name="analisi_python",
        description=(
            "Legge la STRUTTURA di un file Python senza leggerne il corpo: "
            "definizioni con firma e riga (`simboli`), import, chiamate "
            "(`chiamate`, filtrabili con `nome`), usi di un nome, e se il "
            "file compila (`sintassi`). Usalo per orientarti in un file "
            "grande; read_file resta per il contenuto."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Percorso del file .py (relativo alla root o assoluto).",
                },
                "cosa": {
                    "type": "string",
                    "enum": ["simboli", "import", "chiamate", "usi", "sintassi"],
                    "description": "Cosa estrarre (predefinito: simboli).",
                },
                "nome": {
                    "type": "string",
                    "description": ("Filtro: per `chiamate` limita a quelle "
                                    "che contengono questo nome; per `usi` "
                                    "e' il nome da cercare."),
                },
            },
            "required": ["path"],
        },
        handler=handler,
    )
