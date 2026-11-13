"""Answer automata questions typed in plain English.

The solver understands common textbook phrasings offline (no API key):

* "Construct a DFA over {0,1} for strings ending with 01"
* "DFA for strings that start with a and contain bb"
* "Strings with an even number of a's and odd number of b's"
* "Binary numbers divisible by 5", "length at least 3", "exactly two 1s"
* "... and check 0101, 1101"           (tests strings on the new machine)
* "Is 1101 accepted?"                   (tests strings on the current machine)
* "Convert this NFA to a DFA", "Shortest accepted string"

Every answer is computed by the simulation engine in ``automata.py``, so the
accepted/rejected verdicts are exact. Anything the rules do not recognize can be
handed to the optional Gemini generator by the caller.
"""
from __future__ import annotations

from collections import deque
from itertools import product
import re
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from automata import (
    EPS, analyze_machine, determinize, fmt_set, machine_from_spec,
    simulate, verdict,
)

MAX_STATES = 64

NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

EXAMPLE_QUESTIONS = [
    "Construct a DFA over {0,1} for strings ending with 01 and check 1101, 0110",
    "DFA for strings over {a,b} that start with a and contain bb",
    "Strings with an even number of a's and an odd number of b's",
    "Binary numbers divisible by 5. Test 101, 1010, 111",
    "NFA for strings over {a,b} containing aba",
    "Strings over {a,b} that do not contain aa",
    "Is 1101 accepted?",
    "Convert this NFA to a DFA",
]


class NotUnderstood(ValueError):
    """The rule-based parser could not interpret the question."""


# --------------------------------------------------------------------------- #
# Generic DFA construction from a "memory" function
# --------------------------------------------------------------------------- #

def _explore(alphabet: List[str], start, step: Callable, accept: Callable) -> dict:
    """Breadth-first build of a complete DFA whose states are memory keys."""
    names = {start: "q0"}
    queue = deque([start])
    trans: Dict[Tuple[str, str], List[str]] = {}
    while queue:
        key = queue.popleft()
        for symbol in alphabet:
            nxt = step(key, symbol)
            if nxt not in names:
                if len(names) >= MAX_STATES:
                    raise NotUnderstood(f"That language needs more than {MAX_STATES} states.")
                names[nxt] = f"q{len(names)}"
                queue.append(nxt)
            trans[names[key], symbol] = [names[nxt]]
    return {"kind": "DFA", "states": list(names.values()), "alphabet": alphabet[:],
            "start": "q0", "accepts": [n for k, n in names.items() if accept(k)],
            "trans": trans}


def _overlap(memory: str, w: str) -> str:
    """Longest suffix of ``memory`` that is a prefix of ``w`` (KMP state)."""
    for i in range(len(memory) + 1):
        if w.startswith(memory[i:]):
            return memory[i:]
    return ""


class Condition:
    """A regular property with a memory-key DFA and a readable description."""

    def __init__(self, text, start, step, accept):
        self.text, self.start, self.step, self.accept = text, start, step, accept

    def negate(self) -> "Condition":
        text = self.text
        for pos, neg in (("contains ", "does not contain "), ("ends with ", "does not end with "),
                         ("starts with ", "does not start with ")):
            if text.startswith(pos):
                text = neg + text[len(pos):]
                break
        else:
            text = f"NOT ({text})"
        return Condition(text, self.start, self.step, lambda k, f=self.accept: not f(k))


def ends_with(w):
    return Condition(f"ends with {w}", "", lambda k, c: _overlap(k + c, w), lambda k: k == w)


def starts_with(w):
    def step(k, c):
        if k in ("OK", "DEAD"):
            return k
        k += c
        return "OK" if k == w else (k if w.startswith(k) else "DEAD")
    return Condition(f"starts with {w}", "" if w else "OK", step, lambda k: k == "OK")


def contains(w):
    return Condition(f"contains {w}", "",
                     lambda k, c: k if k == w else _overlap(k + c, w), lambda k: k == w)


def count_mod(symbol, k, r=0):
    label = {(2, 0): f"even number of {symbol}'s", (2, 1): f"odd number of {symbol}'s"}
    return Condition(label.get((k, r), f"number of {symbol}'s ≡ {r} (mod {k})"), 0,
                     lambda n, c: (n + (c == symbol)) % k, lambda n: n == r % k)


def count_cmp(symbol, op, n):
    cap = n + 1
    test = {"==": lambda x: x == n, ">=": lambda x: x >= n, "<=": lambda x: x <= n}[op]
    word = {"==": "exactly", ">=": "at least", "<=": "at most"}[op]
    return Condition(f"{word} {n} {symbol}'s", 0,
                     lambda x, c: min(x + (c == symbol), cap), test)


def length_mod(k, r=0):
    label = {(2, 0): "even length", (2, 1): "odd length"}
    return Condition(label.get((k, r), f"length ≡ {r} (mod {k})"), 0,
                     lambda n, c: (n + 1) % k, lambda n: n == r % k)


def length_cmp(op, n):
    test = {"==": lambda x: x == n, ">=": lambda x: x >= n, "<=": lambda x: x <= n}[op]
    word = {"==": "exactly", ">=": "at least", "<=": "at most"}[op]
    return Condition(f"length {word} {n}", 0, lambda x, c: min(x + 1, n + 1), test)


def binary_mod(n):
    return Condition(f"binary value divisible by {n}", 0,
                     lambda v, c: (2 * v + int(c)) % n, lambda v: v == 0)


def combine(conds: List[Condition], mode: str) -> Condition:
    if len(conds) == 1:
        return conds[0]
    agg = all if mode == "and" else any
    return Condition(f" {mode.upper()} ".join(c.text for c in conds),
                     tuple(c.start for c in conds),
                     lambda key, ch: tuple(c.step(k, ch) for c, k in zip(conds, key)),
                     lambda key: agg(c.accept(k) for c, k in zip(conds, key)))


# --------------------------------------------------------------------------- #
# Classic NFAs (for questions that explicitly ask for an NFA)
# --------------------------------------------------------------------------- #

def classic_nfa(kind: str, w: str, alphabet: List[str]) -> dict:
    n = len(w)
    states = [f"q{i}" for i in range(n + 1)]
    trans: Dict[Tuple[str, str], List[str]] = {}

    def add(u, a, v):
        bucket = trans.setdefault((u, a), [])
        if v not in bucket:
            bucket.append(v)

    if kind in ("ends", "contains"):
        for a in alphabet:
            add("q0", a, "q0")
    for i, ch in enumerate(w):
        add(f"q{i}", ch, f"q{i + 1}")
    if kind in ("starts", "contains"):
        for a in alphabet:
            add(f"q{n}", a, f"q{n}")
    return {"kind": "NFA", "states": states, "alphabet": alphabet[:], "start": "q0",
            "accepts": [f"q{n}"], "trans": trans}


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

TOKEN = r"""['"‘’“”]?(?P<w>[A-Za-z0-9]+)['"‘’“”]?"""
SYM = r"""['"‘’“”]?(?P<x>[A-Za-z0-9])['"‘’“”]?(?:'s|’s|s)?"""
NUM = r"(?P<n>\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten)"
NEG = r"(?P<neg>\b(?:not|don't|doesn't|do not|does not|never)\s+)?"

CMP_WORDS = {"exactly": "==", "at least": ">=", "atleast": ">=", "minimum": ">=",
             "minimum of": ">=", "at most": "<=", "atmost": "<=", "maximum": "<=",
             "maximum of": "<=", "no more than": "<=", "no less than": ">="}
CMP = r"(?P<cmp>exactly|at least|atleast|at most|atmost|minimum of|minimum|maximum of|maximum|no more than|no less than)"


COUNT_WORDS = {"two": 2, "three": 3, "four": 4, "2": 2, "3": 3, "4": 4}
CONSEC = (r"(?P<neg>\b(?:not|don't|doesn't|do not|does not|never|without|no)\s+)?"
          r"\b(?:(?:contain|contains|containing|having|has|have|include|includes|with)\s+)?"
          r"(?P<no>no\s+)?(?:(?P<cnt>two|three|four|2|3|4)\s+)?consecutive\s+"
          r"""['"‘’“”]?(?P<w>[A-Za-z0-9]+?)['"‘’“”]?(?:'s|’s|s)?(?![A-Za-z0-9])""")


def _consecutive(m):
    """'consecutive 11', 'two consecutive 1s', 'no 3 consecutive a's' -> repeated block."""
    w = m["w"]
    if len(w) > 1 and len(set(w)) == 1:
        block = w
    else:
        block = w[0] * COUNT_WORDS.get((m["cnt"] or "two").lower(), 2)
    cond = contains(block)
    if m["no"]:
        cond = cond.negate()
    return cond, "contains" if not m["no"] else None, block[0]


# Words that can follow "contains", "ends with" … in a sentence but are never patterns.
STOP_WORDS = {"the", "and", "any", "all", "only", "both", "more", "less", "one", "two",
              "three", "consecutive", "substring", "pattern", "string", "strings", "even",
              "odd", "exactly", "least", "most", "letter", "letters", "symbol", "symbols",
              "an", "same", "different", "either", "each", "every", "some", "no", "at"}


def _valid_token(m, alphabet):
    """Reject English words captured as a pattern (e.g. 'contain consecutive')."""
    w = m.groupdict().get("w")
    if not w:
        return True
    quoted = m.group(0).rstrip()[-1:] in "'\"’”" and not m.group(0).rstrip().endswith("'s")
    if alphabet:
        return set(w) <= set(alphabet)
    if quoted or w.isdigit():
        return True
    return w.isalpha() and len(set(w.lower())) <= 3 and w.lower() not in STOP_WORDS


def _num(text):
    return int(text) if text.isdigit() else NUMBER_WORDS[text.lower()]


# Each rule: (regex, builder(match) -> (Condition, nfa_kind|None, needs_alphabet_chars))
RULES = [
    (CONSEC, _consecutive),
    (NEG + r"\bwithout\s+(?:the\s+|a\s+)?(?:sub-?string\s+)?" + TOKEN,
     lambda m: (contains(m["w"]).negate(), None, m["w"])),
    (NEG + r"\b(?:end|ends|ending|ended)\s+(?:with|in)\s+(?:the\s+)?(?:sub-?string\s+)?" + TOKEN,
     lambda m: (ends_with(m["w"]), "ends", m["w"])),
    (NEG + r"\b(?:start|starts|starting|started|begin|begins|beginning)\s+with\s+(?:the\s+)?(?:sub-?string\s+)?" + TOKEN,
     lambda m: (starts_with(m["w"]), "starts", m["w"])),
    (NEG + r"\b(?:contain|contains|containing|having|has|have|include|includes|including)\s+(?:the\s+|a\s+)?(?:sub-?string|pattern)\s+" + TOKEN,
     lambda m: (contains(m["w"]), "contains", m["w"])),
    (NEG + r"\b(?:contain|contains|containing|include|includes|including)\s+" + TOKEN,
     lambda m: (contains(m["w"]), "contains", m["w"])),
    (r"\b(?P<parity>even|odd)\s+(?:number|no\.?|count)\s+of\s+" + SYM,
     lambda m: (count_mod(m["x"], 2, int(m["parity"].lower() == "odd")), None, m["x"])),
    (r"\b(?:number|no\.?|count)\s+of\s+" + SYM + r"\s+(?:is\s+)?(?P<parity>even|odd)\b",
     lambda m: (count_mod(m["x"], 2, int(m["parity"].lower() == "odd")), None, m["x"])),
    (r"\b(?:number|no\.?|count)\s+of\s+" + SYM + r"\s+(?:is\s+)?(?:divisible\s+by|a\s+multiple\s+of|multiple\s+of)\s+" + NUM,
     lambda m: (count_mod(m["x"], _num(m["n"])), None, m["x"])),
    (r"\b(?:number|no\.?|count)\s+of\s+" + SYM + r"\s+(?:mod|modulo|%)\s+(?P<k>\d+)\s*(?:is|=|==|equals?)\s*(?P<r>\d+)",
     lambda m: (count_mod(m["x"], int(m["k"]), int(m["r"])), None, m["x"])),
    (r"\b(?P<parity>even|odd)\s+length\b|\blength\s+(?:is\s+)?(?P<parity2>even|odd)\b",
     lambda m: (length_mod(2, int((m["parity"] or m["parity2"]).lower() == "odd")), None, "")),
    (r"\blength\s+(?:is\s+)?(?:divisible\s+by|a\s+multiple\s+of|multiple\s+of)\s+" + NUM,
     lambda m: (length_mod(_num(m["n"])), None, "")),
    (r"\blength\s+(?:is\s+|of\s+)?" + CMP + r"\s+" + NUM,
     lambda m: (length_cmp(CMP_WORDS[m["cmp"].lower()], _num(m["n"])), None, "")),
    (r"\blength\s+(?:is\s+|of\s+|=\s*)?" + NUM + r"\b(?!\s*(?:or|and)\s+(?:more|less))",
     lambda m: (length_cmp("==", _num(m["n"])), None, "")),
    (CMP + r"\s+" + NUM + r"\s+" + SYM + r"(?![A-Za-z0-9])",
     lambda m: (count_cmp(m["x"], CMP_WORDS[m["cmp"].lower()], _num(m["n"])), None, m["x"])),
    (r"\b(?:divisible\s+by|multiples?\s+of)\s+" + NUM,
     lambda m: (binary_mod(_num(m["n"])), None, "01")),
]


def parse_alphabet(text: str) -> Optional[List[str]]:
    m = re.search(r"\{([^{}]*)\}", text)
    if m:
        symbols = [s.strip(" '\"") for s in m.group(1).split(",")]
        symbols = [s for s in symbols if s]
        if symbols and all(len(s) == 1 for s in symbols):
            return list(dict.fromkeys(symbols))
    if re.search(r"\bbinary\b", text, re.I):
        return ["0", "1"]
    return None


def parse_conditions(text: str, alphabet: Optional[List[str]] = None):
    found = []
    taken = []
    for pattern, build in RULES:
        for m in re.finditer(pattern, text, re.I):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            if not _valid_token(m, alphabet):
                continue
            cond, nfa_kind, chars = build(m)
            if m.groupdict().get("neg"):
                cond, nfa_kind = cond.negate(), None
            found.append((m.start(), cond, nfa_kind, chars, (m.start(), m.end())))
            taken.append((m.start(), m.end()))
    found.sort(key=lambda item: item[0])
    return found


def parse_test_strings(text: str, alphabet: Optional[List[str]], skip_spans) -> List[str]:
    """Strings to run: quoted words, or words after check/test/is/accept(s)."""
    out: List[str] = []

    def keep(word, pos):
        if any(s <= pos < e for s, e in skip_spans):
            return
        if alphabet and not set(word) <= set(alphabet):
            return
        if word not in out:
            out.append(word)

    for m in re.finditer(r"""(?:check|test|verify|simulate|run|trace|try|accept|accepts|is|are|whether|for\s+(?:the\s+)?(?:input|strings?|w))\s*(?:the\s+)?(?:strings?|inputs?|words?|w)?\s*[:=]?\s*((?:['"‘’“”]?(?:[A-Za-z0-9]+|ε)['"‘’“”]?(?:\s*,\s*|\s+and\s+|\s+or\s+|\s+))*['"‘’“”]?(?:[A-Za-z0-9]+|ε)['"‘’“”]?)""", text, re.I):
        for w in re.finditer(r"[A-Za-z0-9]+|ε", m.group(1)):
            word = w.group(0)
            if word.lower() in {"and", "or", "the", "it", "this", "that", "accepted", "rejected",
                                "string", "strings", "a", "an", "in", "by", "on"}:
                continue
            if word == "ε":
                word = ""
            if alphabet is None and not re.fullmatch(r"[01]+|[ab]+|", word):
                continue
            keep(word, m.start(1) + w.start())
    for m in re.finditer(r"""['"‘“]([A-Za-z0-9]*)['"’”]""", text):
        keep(m.group(1), m.start(1))
    return out


# --------------------------------------------------------------------------- #
# Machine helpers
# --------------------------------------------------------------------------- #

def to_spec(machine: dict, blurb: str, sample: str, batch: List[str]) -> dict:
    return {
        "kind": machine["kind"], "states": ", ".join(machine["states"]),
        "alphabet": ", ".join(machine["alphabet"]), "start": machine["start"],
        "accepts": ", ".join(machine["accepts"]),
        "transitions": [(u, a, ", ".join(v)) for (u, a), v in machine["trans"].items()],
        "sample": sample, "blurb": blurb, "batch": batch or [EPS],
    }


def tidy(machine: dict) -> dict:
    """Rename to q0.. and call non-accepting self-loop trap states 'dead'."""
    dead = [s for s in machine["states"] if s not in machine["accepts"]
            and all(machine["trans"][s, a] == [s] for a in machine["alphabet"])]
    names, i = {}, 0
    for s in machine["states"]:
        if s in dead:
            names[s] = "dead" if len(dead) == 1 else f"dead{len([d for d in dead if names.get(d)])}"
        else:
            names[s] = f"q{i}"
            i += 1
    return {"kind": "DFA", "states": [names[s] for s in machine["states"]],
            "alphabet": machine["alphabet"], "start": names[machine["start"]],
            "accepts": [names[s] for s in machine["accepts"]],
            "trans": {(names[u], a): [names[v[0]]] for (u, a), v in machine["trans"].items()}}


def run_strings(machine: dict, strings: List[str]) -> List[dict]:
    rows = []
    for s in strings:
        steps, ok, final, stuck = simulate(machine, s)
        path = " → ".join(fmt_set(st["after"], single=machine["kind"] == "DFA") for st in steps)
        rows.append({"String": s or EPS, "Result": "✅ Accepted" if ok else "❌ Rejected",
                     "Path": path, "Reason": verdict(machine, steps, ok, final, stuck)[1]})
    return rows


def examples(machine: dict, limit: int = 6, max_len: int = 6):
    accepted, rejected = [], []
    for length in range(max_len + 1):
        for chars in product(machine["alphabet"], repeat=length):
            word = "".join(chars)
            ok = simulate(machine, word)[1]
            bucket = accepted if ok else rejected
            if len(bucket) < limit:
                bucket.append(word or EPS)
            if len(accepted) >= limit and len(rejected) >= limit:
                return accepted, rejected
    return accepted, rejected


def transition_table(machine: dict) -> pd.DataFrame:
    symbols = machine["alphabet"] + ([EPS] if any(a == EPS for _, a in machine["trans"]) else [])
    rows = []
    for s in machine["states"]:
        label = ("→ " if s == machine["start"] else "") + ("* " if s in machine["accepts"] else "") + s
        row = {"State": label}
        for a in symbols:
            row[a] = fmt_set(machine["trans"].get((s, a), []), single=machine["kind"] == "DFA")
        rows.append(row)
    return pd.DataFrame(rows)


def _finish(machine, title, steps_md, tests, new_machine=True, extra=None):
    accepted, rejected = examples(machine)
    sample = tests[0] if tests else (accepted[0] if accepted else "")
    sample = "" if sample == EPS else sample
    batch = list(dict.fromkeys((tests or []) + accepted[:3] + rejected[:3])) or [EPS]
    batch = [b or EPS for b in batch]
    return {
        "title": title,
        "steps": steps_md,
        "machine": machine,
        "table": transition_table(machine),
        "tests": run_strings(machine, tests) if tests else [],
        "accepted_examples": accepted,
        "rejected_examples": rejected,
        "spec": to_spec(machine, title, sample, batch) if new_machine else None,
        "extra": extra,
    }


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def solve(question: str, current: Optional[dict] = None) -> dict:
    """Return a result dict, or raise NotUnderstood."""
    q = " ".join(question.strip().split())
    if not q:
        raise NotUnderstood("Type a question first.")
    lower = q.lower()
    alphabet = parse_alphabet(q)
    found = parse_conditions(q, alphabet)
    spans = [f[4] for f in found] + [m.span() for m in re.finditer(r"\{[^{}]*\}", q)]

    if found:
        chars = "".join(f[3] for f in found)
        if alphabet is None:
            if set(chars) <= {"0", "1"}:
                alphabet = ["0", "1"]
            elif set(chars) <= {"a", "b"}:
                alphabet = ["a", "b"]
            else:
                alphabet = sorted(set(chars) | ({"a", "b"} if chars.isalpha() else {"0", "1"}))
        missing = sorted(set(chars) - set(alphabet))
        if missing:
            raise NotUnderstood(f"Symbol(s) {', '.join(missing)} are not in the alphabet {{{', '.join(alphabet)}}}.")
        if any(f[1].text.startswith("binary") for f in found) and alphabet != ["0", "1"]:
            alphabet = ["0", "1"]
        mode = "or" if re.search(r"\bor\b", q[found[0][4][1]:found[-1][4][0]] if len(found) > 1 else "", re.I) else "and"
        cond = combine([f[1] for f in found], mode)
        tests = parse_test_strings(q, alphabet, spans)
        language = f"L = {{ w ∈ {{{', '.join(alphabet)}}}* | {cond.text} }}"

        wants_nfa = re.search(r"\bnfa\b|non-?deterministic", lower) and not re.search(r"\bdfa\b", lower)
        if wants_nfa and len(found) == 1 and found[0][2]:
            machine = classic_nfa(found[0][2], re.sub(r"[^A-Za-z0-9]", "", found[0][3]), alphabet)
            steps_md = [
                f"**Language:** {language}",
                "**Idea:** the NFA guesses where the pattern occurs; q0 loops on every symbol"
                if found[0][2] != "starts" else "**Idea:** read the prefix first, then loop on everything",
                f"**NFA:** {len(machine['states'])} states, start q0, final {fmt_set(machine['accepts'])}.",
            ]
            return _finish(machine, f"NFA: {cond.text}", steps_md, tests)

        raw = _explore(alphabet, cond.start, cond.step, cond.accept)
        machine = tidy(raw)
        steps_md = [
            f"**Language:** {language}",
            f"**Construction:** each state remembers just enough of the input to decide "
            f"*{cond.text}*, giving **{len(machine['states'])} states**.",
            f"**Start:** {machine['start']}  ·  **Final:** {fmt_set(machine['accepts'])}"
            + ("  ·  **dead** is a trap state." if "dead" in machine["states"] else ""),
        ]
        if wants_nfa:
            steps_md.append("Every DFA is also an NFA, so this machine answers the NFA question too.")
        return _finish(machine, f"DFA: {cond.text}", steps_md, tests)

    # ---- Questions about the machine that is already loaded ---------------- #
    if current is None:
        raise NotUnderstood("Could not recognize a language in that question.")

    if re.search(r"\bconvert|subset construction|equivalent dfa|nfa\s*(?:to|→|->)\s*dfa", lower):
        if current["kind"] == "DFA":
            raise NotUnderstood("The current machine is already a DFA.")
        dfa, subsets = determinize(current)
        rows = [{"DFA state": n, "NFA states": fmt_set(s)} for n, s in subsets.items()]
        steps_md = [
            "**Method:** subset construction — each DFA state is a set of NFA states "
            "(ε-closures included). ∅ is the trap state.",
            f"The NFA with {len(current['states'])} states becomes a DFA with "
            f"**{len(dfa['states'])} states**.",
        ]
        return _finish(dfa, "NFA → DFA (subset construction)", steps_md,
                       parse_test_strings(q, current["alphabet"], spans),
                       extra=("Subset mapping", pd.DataFrame(rows)))

    tests = (parse_test_strings(q, current["alphabet"], spans)
             or parse_test_strings(q, None, spans))
    if re.search(r"shortest|smallest|minimum length", lower) or (not tests and re.search(r"empty language|is the language empty", lower)):
        info = analyze_machine(current)
        shortest = info["shortest"]
        msg = ("The language is **empty** — no accepting state is reachable."
               if shortest is None else f"Shortest accepted string: **{shortest or EPS}**")
        return _finish(current, "Shortest accepted string", [msg], tests, new_machine=False)

    if tests:
        verdicts = run_strings(current, tests)
        steps_md = [f"Ran {len(tests)} string(s) on the current {current['kind']}."]
        return {**_finish(current, "Membership test", steps_md, tests, new_machine=False),
                "tests": verdicts}

    raise NotUnderstood("Could not recognize a language or a string to test in that question.")


def solve_from_spec(spec: dict, question: str) -> dict:
    """Wrap a machine produced elsewhere (e.g. Gemini) in the same answer format."""
    machine, errors, _ = machine_from_spec(spec)
    if errors:
        raise NotUnderstood(" ".join(errors))
    q = " ".join(question.split())
    skip = [m.span() for m in re.finditer(r"\{[^{}]*\}", q)]
    tests = parse_test_strings(q, machine["alphabet"], skip)
    steps_md = [f"**Interpretation (AI):** {spec.get('blurb', '')}",
                "Generated by Gemini, then checked by this app's simulator. "
                "Verify a few examples below before relying on it."]
    return _finish(machine, f"{machine['kind']} (AI-generated)", steps_md, tests)
