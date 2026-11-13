"""Regular expression -> ε-NFA by Thompson's construction.

Syntax (textbook style):
    ab      concatenation
    a|b     union (a+b also means union, as in most automata textbooks)
    a*      Kleene star        a?  optional
    ( )     grouping           ε   the empty string (also written @ or eps)
Symbols are single letters or digits. Spaces are ignored.
"""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Tuple

from automata import EPS

MAX_LENGTH = 200


class RegexError(ValueError):
    pass


class _Builder:
    def __init__(self):
        self.count = 0
        self.edges: List[Tuple[int, str, int]] = []

    def state(self) -> int:
        self.count += 1
        return self.count - 1

    def edge(self, u, symbol, v):
        self.edges.append((u, symbol, v))

    # Each fragment is (start, accept).
    def symbol(self, ch):
        s, f = self.state(), self.state()
        self.edge(s, ch, f)
        return s, f

    def empty(self):
        return self.symbol(EPS)

    def concat(self, a, b):
        self.edge(a[1], EPS, b[0])
        return a[0], b[1]

    def union(self, a, b):
        s, f = self.state(), self.state()
        for frag in (a, b):
            self.edge(s, EPS, frag[0])
            self.edge(frag[1], EPS, f)
        return s, f

    def star(self, a):
        s, f = self.state(), self.state()
        self.edge(s, EPS, a[0])
        self.edge(s, EPS, f)
        self.edge(a[1], EPS, a[0])
        self.edge(a[1], EPS, f)
        return s, f

    def optional(self, a):
        return self.union(a, self.empty())


def _tokenize(regex: str) -> List[str]:
    text = regex.replace("eps", EPS).replace("@", EPS)
    tokens = [ch for ch in text if not ch.isspace()]
    for ch in tokens:
        if not (ch.isalnum() or ch in "|+*?()" or ch == EPS):
            raise RegexError(f"Unsupported character “{ch}”. Use letters, digits, | + * ? ( ) and ε.")
    return tokens


def _parse(tokens: List[str], b: _Builder):
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def expr():
        nonlocal pos
        frag = term()
        while peek() in ("|", "+"):
            pos += 1
            frag = b.union(frag, term())
        return frag

    def term():
        frag = None
        while peek() is not None and peek() not in ("|", "+", ")"):
            nxt = factor()
            frag = nxt if frag is None else b.concat(frag, nxt)
        return frag if frag is not None else b.empty()

    def factor():
        nonlocal pos
        frag = base()
        while peek() in ("*", "?"):
            frag = b.star(frag) if peek() == "*" else b.optional(frag)
            pos += 1
        return frag

    def base():
        nonlocal pos
        tok = peek()
        if tok == "(":
            pos += 1
            frag = expr()
            if peek() != ")":
                raise RegexError("Missing closing parenthesis “)”.")
            pos += 1
            return frag
        if tok in ("*", "?"):
            raise RegexError(f"“{tok}” must follow a symbol or a group.")
        pos += 1
        return b.empty() if tok == EPS else b.symbol(tok)

    frag = expr()
    if pos != len(tokens):
        raise RegexError("Unmatched closing parenthesis “)”.")
    return frag


def regex_to_nfa(regex: str) -> dict:
    """Return a machine dict (same shape as automata.build_machine) and steps."""
    if not regex.strip():
        raise RegexError("Enter a regular expression.")
    if len(regex) > MAX_LENGTH:
        raise RegexError(f"Keep the expression under {MAX_LENGTH} characters.")
    tokens = _tokenize(regex)
    alphabet = sorted({t for t in tokens if t.isalnum() and t != EPS})
    if not alphabet:
        raise RegexError("The expression needs at least one symbol (letter or digit).")
    b = _Builder()
    start, accept = _parse(tokens, b)

    # Rename states q0, q1, ... in breadth-first order from the start state.
    out: Dict[int, List[Tuple[str, int]]] = {}
    for u, sym, v in b.edges:
        out.setdefault(u, []).append((sym, v))
    order, seen, queue = [], {start}, deque([start])
    while queue:
        u = queue.popleft()
        order.append(u)
        for _, v in out.get(u, []):
            if v not in seen:
                seen.add(v)
                queue.append(v)
    names = {u: f"q{i}" for i, u in enumerate(order)}
    trans: Dict[Tuple[str, str], List[str]] = {}
    for u in order:
        for sym, v in out.get(u, []):
            bucket = trans.setdefault((names[u], sym), [])
            if names[v] not in bucket:
                bucket.append(names[v])
    return {"kind": "NFA", "states": [names[u] for u in order], "alphabet": alphabet,
            "start": names[start], "accepts": [names[accept]], "trans": trans}


def regex_spec(regex: str, sample: str = "") -> dict:
    """Editor spec for the app, with sample strings chosen from the language."""
    from itertools import product
    from automata import simulate

    m = regex_to_nfa(regex)
    accepted, rejected = [], []
    for n in range(6):
        for chars in product(m["alphabet"], repeat=n):
            w = "".join(chars)
            (accepted if simulate(m, w)[1] else rejected).append(w or EPS)
    batch = list(dict.fromkeys(accepted[:4] + rejected[:3])) or [EPS]
    if not sample:
        sample = next((w for w in accepted if len(w) >= 2), accepted[0] if accepted else "")
    eps_moves = sum(len(v) for (_, s), v in m["trans"].items() if s == EPS)
    return {
        "kind": "NFA", "states": ", ".join(m["states"]), "alphabet": ", ".join(m["alphabet"]),
        "start": m["start"], "accepts": ", ".join(m["accepts"]),
        "transitions": [(u, s, ", ".join(v)) for (u, s), v in m["trans"].items()],
        "sample": "" if sample == EPS else sample,
        "blurb": (f"Thompson ε-NFA for {regex.strip()}: {len(m['states'])} states, "
                  f"{eps_moves} ε-moves. One start and one accepting state, "
                  "built from small pieces joined by ε-moves."),
        "batch": batch,
    }
