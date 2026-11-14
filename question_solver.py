"""Answer automata questions typed in plain English.

The solver understands common textbook phrasings offline (no API key):

* "Construct a DFA over {0,1} for strings ending with 01"
* "DFA for strings that start with a and contain bb"
* "Strings with an even number of a's and odd number of b's"
* "Binary numbers divisible by 5", "length at least 3", "exactly two 1s"
* "... and check 0101, 1101"           (tests strings on the new machine)
* "Is 1101 accepted?"                   (tests strings on the current machine)
* "Convert this NFA to a DFA", "Shortest accepted string"
* "Third symbol from the end is 1", "every a is followed by b", "only a's",
  "exactly two occurrences of ab", "n_a(w) mod 3 = 1", "|w| >= 2"
* Regular expressions: "DFA for (a+b)*abb", "ε-NFA for a*b*"
* Non-regular requests (palindromes, a^n b^n, equal numbers of a's and b's, ww …)
  are recognised and explained instead of producing a wrong machine.

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
from regex_to_nfa import RegexError, regex_to_nfa

MAX_STATES = 64        # largest machine that is still readable when drawn
EXPLORE_LIMIT = 4096   # states explored before equivalent states are merged

NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

EXAMPLE_QUESTIONS = [
    "Construct a DFA over {0,1} for strings ending with 01 and check 1101, 0110",
    "DFA for strings over {a,b} that start with a and contain bb",
    "Strings with an even number of a's and an odd number of b's",
    "Binary numbers divisible by 5. Test 101, 1010, 111",
    "NFA for strings over {a,b} containing aba",
    "Strings over {a,b} that do not contain aa",
    "NFA for strings over {0,1} whose third symbol from the end is 1",
    "DFA for the regular expression (a+b)*abb. Check abb, aabb, abab",
    "Every a is followed by b. Check abab, aab, ε",
    "DFA for palindromes over {a,b}",
    "Is 1101 accepted?",
    "Convert this NFA to a DFA",
]


class NotUnderstood(ValueError):
    """The rule-based parser could not interpret the question."""


class FinalAnswer(NotUnderstood):
    """A definite answer that is not a machine (e.g. the language is not regular).
    Callers should show the message and must not fall back to an AI generator."""


class NotRegular(FinalAnswer):
    """The requested language is not regular, so no DFA/NFA exists."""


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
                if len(names) >= EXPLORE_LIMIT:
                    raise FinalAnswer(f"That language needs more than {MAX_STATES} states, which is "
                                      "too large to draw clearly. Try a smaller number.")
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
            text = text.replace(" is ", " is not ", 1) if " is " in text else f"NOT ({text})"
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
    _positive(k)
    label = {(2, 0): f"even number of {symbol}'s", (2, 1): f"odd number of {symbol}'s"}
    return Condition(label.get((k, r), f"number of {symbol}'s ≡ {r} (mod {k})"), 0,
                     lambda n, c: (n + (c == symbol)) % k, lambda n: n == r % k)


def count_cmp(symbol, op, n):
    if op == "<=" and n < 0:
        return empty_language()
    cap = max(n, 0) + 1
    test = {"==": lambda x: x == n, ">=": lambda x: x >= n, "<=": lambda x: x <= n}[op]
    word = {"==": "exactly", ">=": "at least", "<=": "at most"}[op]
    return Condition(f"{word} {n} {symbol}'s", 0,
                     lambda x, c: min(x + (c == symbol), cap), test)


def length_mod(k, r=0):
    _positive(k)
    label = {(2, 0): "even length", (2, 1): "odd length"}
    return Condition(label.get((k, r), f"length ≡ {r} (mod {k})"), 0,
                     lambda n, c: (n + 1) % k, lambda n: n == r % k)


def length_cmp(op, n):
    if op == "<=" and n < 0:
        return empty_language()
    test = {"==": lambda x: x == n, ">=": lambda x: x >= n, "<=": lambda x: x <= n}[op]
    word = {"==": "exactly", ">=": "at least", "<=": "at most"}[op]
    return Condition(f"length {word} {n}", 0, lambda x, c: min(x + 1, n + 1), test)


def first_last(same: bool):
    """First and last symbol equal (or different). ε has no first symbol, so it is rejected;
    a single symbol starts and ends with itself."""
    def step(key, c):
        return (c, c) if key is None else (key[0], c)
    if same:
        return Condition("first symbol = last symbol (ε excluded)", None, step,
                         lambda k: k is not None and k[0] == k[1])
    return Condition("first symbol ≠ last symbol", None, step,
                     lambda k: k is not None and k[0] != k[1])


def _nth(k):
    return f"{k}{'th' if 10 <= k % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(k % 10, 'th')}"


def _positive(k, what="Divisor"):
    if k < 1:
        raise FinalAnswer(f"{what} must be at least 1 (division by {k} is undefined).")
    return k


def binary_mod(n, r=0):
    _positive(n)
    text = (f"binary value divisible by {n}" if r == 0 else
            f"binary value ≡ {r} (mod {n})")
    return Condition(text, 0, lambda v, c: (2 * v + int(c)) % n, lambda v: v == r)


def from_end(k, x):
    """k-th symbol from the right is x (needs |w| >= k)."""
    _positive(k, "Position")
    ordinal = {1: "last symbol", 2: "second-last symbol"}.get(k, f"{_nth(k)} symbol from the end")
    return Condition(f"{ordinal} is {x}", "", lambda m, c: (m + c)[-k:],
                     lambda m: len(m) == k and m[0] == x)


def from_start(k, x):
    """k-th symbol from the left is x (needs |w| >= k)."""
    _positive(k, "Position")
    ordinal = {1: "first symbol", 2: "second symbol", 3: "third symbol"}.get(k, f"{_nth(k)} symbol")

    def step(key, c):
        if key in ("OK", "BAD"):
            return key
        pos = key + 1
        return ("OK" if c == x else "BAD") if pos == k else pos
    return Condition(f"{ordinal} is {x}", 0, step, lambda key: key == "OK")


def followed_by(x, y):
    """Every x is immediately followed by y."""
    def merge(a, b):
        if a.startswith(b):
            return a
        if b.startswith(a):
            return b
        return "#DEAD"

    def step(pending, c):
        if pending == "#DEAD":
            return pending
        if pending:
            if c != pending[0]:
                return "#DEAD"
            pending = pending[1:]
        return merge(pending, y) if c == x else pending
    return Condition(f"every {x} is immediately followed by {y}", "", step, lambda p: p == "")


def preceded_by(x, y):
    """Every x is immediately preceded by y."""
    n = len(y)

    def step(last, c):
        if last == "#DEAD":
            return last
        if c == x and not (len(last) == n and last == y):
            return "#DEAD"
        return (last + c)[-n:]
    return Condition(f"every {x} is immediately preceded by {y}", "", step, lambda k: k != "#DEAD")


def only_symbol(x):
    return Condition(f"only {x}'s", True, lambda ok, c: ok and c == x, lambda ok: ok)


def occurrences(w, op, n):
    """Number of (overlapping) occurrences of w compared with n."""
    if len(w) == 1:
        return count_cmp(w, op, n)
    test = {"==": lambda x: x == n, ">=": lambda x: x >= n, "<=": lambda x: x <= n}[op]
    word = {"==": "exactly", ">=": "at least", "<=": "at most"}[op]

    def step(key, c):
        state, count = key
        state = _overlap(state + c, w)
        return state, min(count + (state == w), n + 1)
    return Condition(f"{word} {n} occurrence{'s' if n != 1 else ''} of {w}", ("", 0), step,
                     lambda key: test(key[1]))


def universal():
    return Condition("any string (L = Σ*)", 0, lambda k, c: 0, lambda k: True)


def empty_language():
    return Condition("no string (L = ∅)", 0, lambda k, c: 0, lambda k: False)


def only_epsilon():
    return Condition("only the empty string ε", 0, lambda k, c: 1, lambda k: k == 0)


def combine_mixed(conds: List[Condition], connectors: List[str]) -> Condition:
    """AND binds tighter than OR: a and b or c  ==  (a and b) or c."""
    groups, current = [], [conds[0]]
    for cond, conn in zip(conds[1:], connectors):
        if conn == "or":
            groups.append(current)
            current = [cond]
        else:
            current.append(cond)
    groups.append(current)
    return combine([combine(g, "and") for g in groups], "or")


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

    if kind.startswith("kth_end"):
        k = int(kind.split(":")[1])
        states = [f"q{i}" for i in range(k + 1)]
        for a in alphabet:
            add("q0", a, "q0")
        add("q0", w, "q1")
        for i in range(1, k):
            for a in alphabet:
                add(f"q{i}", a, f"q{i + 1}")
        return {"kind": "NFA", "states": states, "alphabet": alphabet[:], "start": "q0",
                "accepts": [f"q{k}"], "trans": trans}
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


def union_nfa(kinds: List[str], words: List[str], alphabet: List[str]):
    """Textbook NFA for 'contains/ends with/starts with w1 or w2 or ...'."""
    trans: Dict[Tuple[str, str], List[str]] = {}

    def add(u, a, v):
        bucket = trans.setdefault((u, a), [])
        if v not in bucket:
            bucket.append(v)

    if len(set(kinds)) == 1 and kinds[0] in ("contains", "ends"):
        # One looping start state, one chain per pattern, one shared final state.
        states, final = ["q0"], None
        for a in alphabet:
            add("q0", a, "q0")
        chains = []
        for w in words:
            chain = ["q0"] + [None] * (len(w) - 1)
            for i in range(1, len(w)):
                chain[i] = f"q{len(states)}"
                states.append(chain[i])
            chains.append(chain)
        final = f"q{len(states)}"
        states.append(final)
        for w, chain in zip(words, chains):
            nodes = chain + [final]
            for i, ch in enumerate(w):
                add(nodes[i], ch, nodes[i + 1])
        if kinds[0] == "contains":
            for a in alphabet:
                add(final, a, final)
        idea = ("q0 loops on every symbol and guesses where a pattern begins; each pattern has its "
                "own chain of states and all chains meet in one accepting state"
                + (" that loops on every symbol (the rest of the string can be anything)."
                   if kinds[0] == "contains" else " (it must be the end of the input)."))
        return {"kind": "NFA", "states": states, "alphabet": alphabet[:], "start": "q0",
                "accepts": [final], "trans": trans}, idea
    # Mixed kinds: a new start state with ε-moves into one classic NFA per condition.
    states, accepts = ["q0"], []
    for kind, w in zip(kinds, words):
        part = classic_nfa(kind, w, alphabet)
        offset = len(states)
        rename = {s: f"q{offset + i}" for i, s in enumerate(part["states"])}
        states += list(rename.values())
        add("q0", EPS, rename[part["start"]])
        for (u, a), targets in part["trans"].items():
            for v in targets:
                add(rename[u], a, rename[v])
        accepts += [rename[x] for x in part["accepts"]]
    idea = ("a new start state q0 jumps by ε-moves into one small NFA per condition; the string is "
            "accepted if any of them accepts (union construction).")
    return {"kind": "NFA", "states": states, "alphabet": alphabet[:], "start": "q0",
            "accepts": accepts, "trans": trans}, idea


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

Q = r"""['"‘’“”]?"""
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


ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
            "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6}
ORD = r"(?P<k>first|second|third|fourth|fifth|sixth|\d+(?:st|nd|rd|th))"
POSUNIT = r"(?:symbol|letter|character|char|bit|digit|position|element)"
IS = r"\s+(?:is|=|must\s+be|should\s+be|equals?|being|as)\s+(?P<isnot>not\s+)?"
XSYM = r"""['"‘’“”]?(?P<x>[A-Za-z0-9])['"‘’“”]?(?![A-Za-z0-9])"""
YTOK = r"""(?:at\s+least\s+one\s+|an?\s+|the\s+)?['"‘’“”]?(?P<y>[A-Za-z0-9]+?)['"‘’“”]?(?:'s|’s|s)?(?![A-Za-z0-9])"""
TIMES = {"once": 1, "twice": 2, "thrice": 3}
CMPW = {"more than": ">", "greater than": ">", "bigger than": ">", "longer than": ">",
        "less than": "<", "fewer than": "<", "smaller than": "<", "shorter than": "<"}


def _ordinal(k):
    k = k.lower()
    return ORDINALS.get(k) or int(re.sub(r"\D", "", k))


def _neg_if(m, cond, kind):
    return (cond.negate(), None) if m.groupdict().get("isnot") else (cond, kind)


def _kth(m):
    k = _ordinal(m["k"])
    end = bool(m["last"]) or (m["side"] or "").lower() in ("end", "right", "last")
    cond = from_end(k, m["x"]) if end else from_start(k, m["x"])
    cond, kind = _neg_if(m, cond, f"kth_end:{k}" if end else None)
    return cond, kind, m["x"]


def _first_last_symbol(m):
    end = m["pos"].lower() in ("last", "rightmost", "final", "ending")
    cond = from_end(1, m["x"]) if end else from_start(1, m["x"])
    cond, _ = _neg_if(m, cond, None)
    return cond, None, m["x"]


def _ops(op, n):
    """Map a comparison to (op, n) with op in ==, >=, <= (plus 'ne')."""
    return {">": (">=", n + 1), "<": ("<=", n - 1), ">=": (">=", n), "≥": (">=", n),
            "<=": ("<=", n), "≤": ("<=", n), "=": ("==", n), "==": ("==", n),
            "!=": ("ne", n), "≠": ("ne", n)}[op]


def _length_op(op, n):
    op, n = _ops(op, n)
    return length_cmp("==", n).negate() if op == "ne" else length_cmp(op, n)


def _count_op(x, op, n):
    op, n = _ops(op, n)
    return count_cmp(x, "==", n).negate() if op == "ne" else count_cmp(x, op, n)


def _times(text):
    text = text.lower().strip()
    if text in TIMES:
        return TIMES[text]
    return _num(text.split()[0])



# Each rule: (regex, builder(match) -> (Condition, nfa_kind|None, needs_alphabet_chars))
SAME = r"(?P<rel>same|identical|equal|different|distinct|not\s+the\s+same|a\s+different)"
UNIT = r"(?:symbols?|letters?|characters?|chars?|digits?|bits?|alphabets?)"


def _first_last(m):
    rel = re.sub(r"\s+", " ", m["rel"].lower())
    return first_last(rel in ("same", "identical", "equal")), None, ""


RULES = [
    (CONSEC, _consecutive),
    # k-th symbol from the end / start
    (ORD + r"[\s-]+(?:" + POSUNIT + r"\s+)?(?:from\s+(?:the\s+)?(?P<side>end|right|last|left|start|beginning|front)"
     r"|(?P<last>last|from\s+last|to\s+last|to\s+the\s+last))(?:\s+" + POSUNIT + r")?" + IS + XSYM, _kth),
    (ORD + r"[\s-]+" + POSUNIT + r"(?:\s+(?:of\s+the\s+string|from\s+(?:the\s+)?(?:left|start|beginning|front)))?" + IS + XSYM,
     lambda m: (*_neg_if(m, from_start(_ordinal(m["k"]), m["x"]), None), m["x"])),
    (r"\b(?:the\s+)?penultimate\s+" + POSUNIT + IS + XSYM,
     lambda m: (*_neg_if(m, from_end(2, m["x"]), "kth_end:2"), m["x"])),
    (r"\b(?P<pos>first|last|leftmost|rightmost|final)\s+" + POSUNIT + IS + XSYM, _first_last_symbol),
    # every x followed / preceded by y
    (r"\b(?:every|each|all|any)\s+(?:occurrence\s+of\s+)?(?:the\s+)?(?:symbol\s+)?" + Q + r"(?P<x>[A-Za-z0-9])" + Q + r"(?:'s|’s|s)?"
     r"\s+(?:in\s+(?:the|a)\s+string\s+)?(?:is\s+|are\s+|must\s+be\s+|should\s+be\s+)?(?:immediately\s+|directly\s+)?"
     r"(?P<dir>followed|preceded)\s+by\s+" + YTOK,
     lambda m: ((followed_by if m["dir"].lower() == "followed" else preceded_by)(m["x"], m["y"]),
                None, m["x"] + m["y"])),
    # only a's
    (r"\b(?:only|just|exclusively|entirely\s+of|solely\s+of)\s+" + Q + r"(?P<x>[A-Za-z0-9])" + Q + r"(?:'s|’s|s)(?![A-Za-z0-9])",
     lambda m: (only_symbol(m["x"]), None, m["x"])),
    (r"\bof\s+" + Q + r"(?P<x>[A-Za-z0-9])" + Q + r"(?:'s|’s|s)\s+only\b",
     lambda m: (only_symbol(m["x"]), None, m["x"])),
    # occurrences of a substring
    (r"\b(?:(?P<cmp>exactly|at\s+least|at\s+most|no\s+more\s+than|no\s+less\s+than)\s+)?" + NUM +
     r"\s+(?:occurrences?|instances?|copies|appearances?)\s+of\s+(?:the\s+)?(?:sub-?string\s+|pattern\s+)?" + TOKEN,
     lambda m: (occurrences(m["w"], CMP_WORDS.get(re.sub(r"\s+", " ", (m["cmp"] or "exactly").lower()), "=="),
                            _num(m["n"])), None, m["w"])),
    (r"\b(?:contains?|containing|has|having|with)\s+(?:the\s+)?(?:sub-?string\s+|pattern\s+)?" + TOKEN +
     r"\s+(?P<cmp>exactly\s+|at\s+least\s+|at\s+most\s+)?(?P<times>once|twice|thrice|\d+\s+times|(?:one|two|three|four|five)\s+times)\b",
     lambda m: (occurrences(m["w"], CMP_WORDS.get((m["cmp"] or "exactly").strip().lower(), "=="),
                            _times(m["times"])), None, m["w"])),
    # binary odd / even, remainders
    (r"\b(?P<par>odd|even)\s+binary\s+(?:numbers?|integers?|values?)",
     lambda m: (binary_mod(2, int(m["par"].lower() == "odd")), None, "01")),
    (r"\bbinary\s+(?:numbers?|strings?|integers?|representations?)\s+(?:that\s+are\s+|which\s+are\s+|representing\s+|of\s+)?(?P<par>odd|even)\b(?!\s+(?:number|no\.?|count)\s+of|\s+length)",
     lambda m: (binary_mod(2, int(m["par"].lower() == "odd")), None, "01")),
    (r"\bremainder\s+(?P<r>\d+)\s+when\s+divided\s+by\s+(?P<n>\d+)",
     lambda m: (binary_mod(int(m["n"]), int(m["r"])), None, "01")),
    # no a's
    (r"\b(?:no|zero)\s+" + Q + r"(?P<x>[A-Za-z0-9])" + Q + r"(?:'s|’s|s)(?![A-Za-z0-9])",
     lambda m: (count_cmp(m["x"], "==", 0), None, m["x"])),
    # more/fewer than n a's;  number of a's >= 2
    (r"\b(?P<cw>more|fewer|less|greater)\s+than\s+" + NUM + r"\s+" + SYM + r"(?![A-Za-z0-9])",
     lambda m: (_count_op(m["x"], ">" if m["cw"].lower() in ("more", "greater") else "<", _num(m["n"])), None, m["x"])),
    (r"\b(?:number|no\.?|count)\s+of\s+" + SYM + r"\s*(?:is\s*)?(?P<op>>=|<=|==|!=|=|>|<|≥|≤|≠)\s*(?P<n>\d+)",
     lambda m: (_count_op(m["x"], m["op"], int(m["n"])), None, m["x"])),
    (r"\b(?:number|no\.?|count)\s+of\s+" + SYM + r"\s+(?:is\s+)?(?P<cw>more\s+than|greater\s+than|less\s+than|fewer\s+than)\s+" + NUM,
     lambda m: (_count_op(m["x"], CMPW[re.sub(r"\s+", " ", m["cw"].lower())], _num(m["n"])), None, m["x"])),
    # length with operators / words
    (r"\blength\s*(?:is\s*|of\s*)?(?P<op>>=|<=|==|!=|=|>|<|≥|≤|≠)\s*(?P<n>\d+)",
     lambda m: (_length_op(m["op"], int(m["n"])), None, "")),
    (r"\blength\s+(?:is\s+)?(?P<cw>more\s+than|greater\s+than|less\s+than|fewer\s+than|smaller\s+than|bigger\s+than)\s+" + NUM,
     lambda m: (_length_op(CMPW[re.sub(r"\s+", " ", m["cw"].lower())], _num(m["n"])), None, "")),
    (r"\b(?P<cw>longer|shorter)\s+than\s+" + NUM,
     lambda m: (_length_op(">" if m["cw"].lower() == "longer" else "<", _num(m["n"])), None, "")),
    (r"\blength\s+(?:of\s+)?" + NUM + r"\s+or\s+(?P<more>more|greater|less|fewer|smaller)",
     lambda m: (length_cmp(">=" if m["more"].lower() in ("more", "greater") else "<=", _num(m["n"])), None, "")),
    (r"\blength\s+(?:mod|modulo|%)\s+(?P<k>\d+)\s*(?:is|=|==|equals?)\s*(?P<r>\d+)",
     lambda m: (length_mod(int(m["k"]), int(m["r"])), None, "")),
    (r"\blength\s*(?:is\s*)?(?:≡|congruent\s+to)\s*(?P<r>\d+)\s*\(?\s*mod\s+(?P<k>\d+)\s*\)?",
     lambda m: (length_mod(int(m["k"]), int(m["r"])), None, "")),
    (r"\bnon-?\s?empty\s+strings?\b", lambda m: (length_cmp(">=", 1), None, "")),
    (r"\b(?:start|starts|starting|begin|begins|beginning)\s+and\s+(?:end|ends|ending)\s+"
     r"(?:with|in)\s+(?:the\s+)?" + SAME + r"\s+" + UNIT, _first_last),
    (r"\b(?:first|starting|leftmost)\s+and\s+(?:last|ending|rightmost)\s+" + UNIT +
     r"\s+(?:are|is|being)?\s*(?:the\s+)?" + SAME, _first_last),
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
    (r"\b(?:divisible\s+by|multiples?\s+of)\s+" + NUM +
     r"(?:\s+(?:with|leaving|leaves|giving|gives)\s+(?:a\s+)?remainder\s+(?:of\s+)?(?P<r>\d+))?",
     lambda m: (binary_mod(_num(m["n"]), int(m["r"] or 0)), None, "01")),
    (r"\b(?:value|number|numbers|integers?)\s+(?:is\s+|are\s+)?(?:mod|modulo|%)\s+(?P<k>\d+)\s*(?:is|=|==|equals?)\s*(?P<r>\d+)",
     lambda m: (binary_mod(int(m["k"]), int(m["r"])), None, "01")),
]

# Languages that need no other condition ("all strings", "only ε", "∅").
SPECIAL = [
    (r"\bonly\s+(?:the\s+)?(?:empty\s+string|null\s+string|ε|epsilon|λ)|\{\s*ε\s*\}|L\s*=\s*\{\s*ε\s*\}", only_epsilon),
    (r"\b(?:no\s+strings?|empty\s+(?:language|set)|accepts?\s+nothing|rejects?\s+(?:all|every|everything)|L\s*=\s*(?:∅|\{\s*\}|phi))|∅", empty_language),
    (r"\b(?:all|every|any)\s+(?:possible\s+)?(?:binary\s+)?strings?\b|Σ\s*\*|sigma\s*\*|\ball\s+inputs?\b", universal),
]


# --------------------------------------------------------------------------- #
# Non-regular requests: answer honestly instead of building a wrong machine.
# --------------------------------------------------------------------------- #

NONREGULAR = [
    (r"\bpalindrom", "palindromes",
     "Take w = a^p b a^p (p = pumping length). Pumping inside the first a-block changes "
     "its length but not the last block, so the string is no longer a palindrome."),
    (r"([a-z0-9])\s*\^\s*\{?\s*\d*\s*n\s*\}?.*?([a-z0-9])\s*\^\s*\{?\s*\d*\s*n\b", "aⁿbⁿ-style languages",
     "Take w = a^p b^p. Any pumpable part lies in the a's, so pumping gives a^(p+k) b^p, "
     "which has unequal counts. A DFA would need to count an unbounded number of a's."),
    (r"\bn\s+['\"]?([a-z0-9])['\"]?(?:'s|s)?\s+followed\s+by\s+n\s+", "n a's followed by n b's",
     "Take w = a^p b^p; pumping the a's breaks the equal count."),
    (r"\b(?:equal|same)\s+(?:number|no\.?|count|amount)s?\s+of\s+['\"]?[a-z0-9]['\"]?(?:'s|s)?\s+and\s+['\"]?[a-z0-9]['\"]?(?:'s|s)?(?![a-z0-9])",
     "equal numbers of two symbols",
     "Take w = a^p b^p; pumping the a's changes their count only. A DFA has finitely many "
     "states, so it cannot keep an unbounded difference between the two counts."),
    (r"\b(?:more|fewer|less)\s+['\"]?[a-z0-9]['\"]?(?:'s|s)\s+than\s+['\"]?[a-z0-9]['\"]?(?:'s|s)?\b", "comparing two counts",
     "Take w = a^p b^(p+1) (for 'more b's than a's'); pumping up the a's makes the comparison fail."),
    (r"\bww\b|\bw\s*w\s*(?:\^?\s*r|ᴿ)?\b(?!\s*\()|\bw\s*w\^?R\b|\bstrings?\s+(?:repeated|written)\s+twice|\b(?:of\s+the\s+)?form\s+ww",
     "ww / wwᴿ (a string followed by a copy or its reverse)",
     "Take w = a^p b a^p b; pumping the first a-block makes the two halves differ."),
    (r"\b(?:prime)\b", "prime lengths / prime counts",
     "The gaps between primes grow without bound, but pumping produces lengths in an "
     "arithmetic progression, which must hit a non-prime."),
    (r"\b(?:perfect\s+square|length\s+is\s+a\s+square|square\s+length|length\s+(?:is\s+)?a\s+power\s+of\s+(?:2|two))",
     "lengths that are squares or powers of 2",
     "Consecutive squares (or powers of 2) grow further apart, but pumping adds a fixed "
     "amount each time, so some pumped length falls in a gap."),
    (r"\b(?:balanced|matching|well[- ]formed|properly\s+nested)\s+(?:parenthes|brackets?)", "balanced parentheses",
     "Take w = (^p )^p; pumping the opening brackets leaves them unmatched."),
]


def check_regular(text: str):
    if re.search(r"\bn\s*(?:<|≤|<=)\s*\d+|\bfinite\b", text, re.I):
        return  # bounded n → finite, hence regular
    for pattern, name, proof in NONREGULAR:
        if re.search(pattern, text, re.I):
            raise NotRegular(
                f"No DFA or NFA exists for this: {name} form a **non-regular** language. "
                f"A finite automaton has only finitely many states, so it cannot remember an "
                f"unbounded amount of the input. Pumping-lemma sketch: {proof} "
                "(A pushdown automaton or a Turing machine is needed instead.)")


# --------------------------------------------------------------------------- #
# Text normalisation and regular expressions inside questions
# --------------------------------------------------------------------------- #

PATTERN_KW = (r"contains?|containing|includes?|including|having|has|have|ends?\s+with|ending\s+with|ends?\s+in|"
              r"starts?\s+with|starting\s+with|begins?\s+with|beginning\s+with")
NOT_PATTERNS = STOP_WORDS | {"ends", "end", "starts", "start", "begins", "has", "have", "is", "are",
                             "contains", "contain", "length", "number", "every", "even", "odd",
                             "as", "substring", "substrings", "check", "test", "its", "it"}


def _looks_like_pattern(tok: str) -> bool:
    tok = tok.strip("'\"‘’“”")
    if not tok or tok.lower() in NOT_PATTERNS:
        return False
    return tok.isdigit() or (tok.isalnum() and len(set(tok.lower())) <= 3)


def _expand_pattern_lists(q: str) -> str:
    """'contains 00 or 11' -> 'contains 00 or contains 11' (also and, commas, ends/starts with)."""
    rx = re.compile(r"\b(" + PATTERN_KW + r")\s+(?:the\s+)?(?:sub-?strings?\s+|patterns?\s+)?"
                    r"((?:['\"‘’“”]?[A-Za-z0-9]+['\"‘’“”]?\s*,\s*)*['\"‘’“”]?[A-Za-z0-9]+['\"‘’“”]?)"
                    r"\s*,?\s+(or|and)\s+(['\"‘’“”]?[A-Za-z0-9]+['\"‘’“”]?)(?![A-Za-z0-9'’])", re.I)

    def expand(m):
        first = [t.strip() for t in m.group(2).split(",")]
        last = m.group(4)
        if not all(_looks_like_pattern(t) for t in first + [last]):
            return m.group(0)
        kw, conj = m.group(1), m.group(3)
        return f" {conj} ".join(f"{kw} {t}" for t in first + [last])
    return rx.sub(expand, q)


def normalize(q: str) -> str:
    """Rewrite common notations into the phrasings the rules understand."""
    q = re.sub(r"\b[nN]\s*_?\s*\{?\s*([A-Za-z0-9])\s*\}?\s*\(\s*w\s*\)", r"number of \1's", q)
    q = re.sub(r"#\s*_?\s*([A-Za-z0-9])\s*(?:\(\s*w\s*\))?", r"number of \1's ", q)
    q = re.sub(r"\|\s*w\s*\|\s*_\s*\{?([A-Za-z0-9])\}?", r"number of \1's", q)
    q = re.sub(r"\|\s*w\s*\|", "length", q)
    q = re.sub(r"\bneither\s+(.+?)\s+nor\s+(.+?)(?=[.;,?]|\s+and\s+check|\s+check|$)",
               r"not \1 and not \2", q, flags=re.I)
    q = re.sub(r"\b(contains?|containing|having|has|have|ends?\s+with|ending\s+with|starts?\s+with|starting\s+with|begins?\s+with|beginning\s+with)\s+"
               r"(?:both\s+)(\S+)\s+and\s+(\S+)", r"\1 \2 and \1 \3", q, flags=re.I)
    q = re.sub(r"\b(contains?|containing|having|has|have|ends?\s+with|ending\s+with|starts?\s+with|starting\s+with|begins?\s+with|beginning\s+with)\s+"
               r"(?:either\s+)(\S+)\s+or\s+(\S+)", r"\1 \2 or \1 \3", q, flags=re.I)
    q = _expand_pattern_lists(q)
    q = re.sub(r"\b(?:number|no\.?|count)\s+of\s+(['\"]?[A-Za-z0-9]['\"]?(?:'s|s)?)\s+and\s+(['\"]?[A-Za-z0-9]['\"]?(?:'s|s)?)\s+(?:are\s+|is\s+)?both\s+(even|odd)",
               r"\3 number of \1 and \3 number of \2", q, flags=re.I)
    return q


REGEX_CHARS = r"[A-Za-z0-9ε()+|*?]"


def find_regex(q: str) -> Optional[str]:
    """A regular expression written in the question, e.g. (a+b)*abb or a*b*."""
    candidates = []
    for m in re.finditer(r"(?:regular\s+expression|regex|\bR\.?E\.?|of\s+the\s+form|in\s+the\s+form|\bL\s*=|"
                  r"language\s+(?:of|given\s+by|described\s+by|denoted\s+by)|given\s+by|described\s+by|denoted\s+by|"
                  r"(?:dfa|nfa|automaton)\s+for)\s*[:=]?\s*(?:the\s+)?(?:strings?\s+)?(?P<re>[A-Za-z0-9ε()+|*?\s]+?)"
                  r"(?=\s*(?:[.,;]|\band\b|\bcheck\b|\btest\b|\bover\b|$))", q, re.I):
        words = m["re"].split()
        english = [i for i, w in enumerate(words) if w.isalpha() and len(set(w.lower())) >= 3]
        if english:  # "DFA for the regular expression (a+b)*": keep only what follows the words
            words = words[english[-1] + 1:]
        if words:
            candidates.append("".join(words))
    candidates += re.findall(r"(?<![A-Za-z0-9'’])(" + REGEX_CHARS + r"{2,})(?![A-Za-z0-9'’])", q)
    for cand in candidates:
        cand = cand.rstrip("?")  # a question mark at the end is punctuation, not "optional"
        if (re.search(r"[*()|+?]", cand) and re.search(r"[A-Za-z0-9]", cand)
                and cand.count("(") == cand.count(")") and not re.fullmatch(r"\d+\+\d+", cand)):
            try:
                regex_to_nfa(cand)
            except RegexError:
                continue
            return cand
    return None


def parse_alphabet(text: str) -> Optional[List[str]]:
    m = re.search(r"\{([^{}]*)\}", text)
    if m:
        symbols = [s.strip(" '\"") for s in m.group(1).split(",")]
        symbols = [s for s in symbols if s]
        if symbols and all(len(s) == 1 for s in symbols):
            return list(dict.fromkeys(symbols))
    m = re.search(r"\b(?:over|alphabet|symbols?)\s+(?:the\s+)?(?:alphabet\s+|symbols?\s+)?(?:Σ\s*=?\s*)?"
                  r"((?:[A-Za-z0-9]\s*,\s*)*[A-Za-z0-9]\s*,?\s*and\s+[A-Za-z0-9])(?![A-Za-z0-9'’])", text, re.I)
    if m:
        return list(dict.fromkeys(re.findall(r"[A-Za-z0-9]", m.group(1).replace("and", ""))))
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
    text = re.sub(r"\b(?:the\s+)?(?:empty|null)\s+string\b|\bepsilon\b|λ", "ε", text, flags=re.I)

    def keep(word, pos, loose=False):
        if any(s <= pos < e for s, e in skip_spans):
            return
        if alphabet and not set(word) <= set(alphabet):
            # In a check list, keep strings with stray symbols so the user sees them rejected.
            if not (loose and set(word) & set(alphabet)):
                return
        if word not in out:
            out.append(word)

    for m in re.finditer(r"""\bis\s+['"‘“]?([A-Za-z0-9]+|ε)['"’”]?\s+(?:accepted|rejected|in\s+(?:the\s+)?(?:language|L))""", text, re.I):
        word = "" if m.group(1) == "ε" else m.group(1)
        if not alphabet or set(word) <= set(alphabet):
            keep(word, m.start(1))

    for m in re.finditer(r"""(?:check|test|verify|simulate|run|trace|try|accept|accepts|is|are|whether|for\s+(?:the\s+)?(?:input|strings?|w))\s*(?:the\s+)?(?:strings?|inputs?|words?|w)?\s*[:=]?\s*((?:['"‘’“”]?(?:[A-Za-z0-9]+|ε)['"‘’“”]?(?:\s*,\s*|\s+and\s+|\s+or\s+|\s+))*['"‘’“”]?(?:[A-Za-z0-9]+|ε)['"‘’“”]?)""", text, re.I):
        for w in re.finditer(r"[A-Za-z0-9]+|ε", m.group(1)):
            word = w.group(0)
            is_list = "," in m.group(1)  # "Check a, aba, ab": short words are real inputs here
            if word.lower() in {"and", "or", "the", "it", "this", "that", "accepted", "rejected",
                                "string", "strings", "in", "by", "on"}:
                continue
            if word.lower() in {"a", "an"} and not (is_list and alphabet and set(word) <= set(alphabet)):
                continue
            if word == "ε":
                word = ""
            if alphabet is None and not re.fullmatch(r"[01]+|[ab]+|", word):
                continue
            keep(word, m.start(1) + w.start(), loose=is_list or word.isdigit())
    for m in re.finditer(r"""(?<![A-Za-z0-9])['"‘“]([A-Za-z0-9]*|ε)['"’”]""", text):
        keep("" if m.group(1) == "ε" else m.group(1), m.start(1), loose=True)
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


def _reduce(dfa: dict) -> dict:
    """Merge states that behave identically, so the answer has the fewest possible states.

    Works on the complete DFAs this module builds: drop unreachable states, then split
    {accepting, non-accepting} until states in a block agree on every symbol.
    """
    alphabet, trans = dfa["alphabet"], dfa["trans"]
    order, seen = [dfa["start"]], {dfa["start"]}
    for s in order:                       # breadth-first: reachable states in a stable order
        for a in alphabet:
            t = trans[s, a][0]
            if t not in seen:
                seen.add(t)
                order.append(t)
    finals = set(dfa["accepts"])
    block = {s: int(s in finals) for s in order}
    count = len(set(block.values()))
    while True:
        ids, new = {}, {}
        for s in order:
            sig = (block[s],) + tuple(block[trans[s, a][0]] for a in alphabet)
            new[s] = ids.setdefault(sig, len(ids))
        block = new
        if len(ids) == count:
            break
        count = len(ids)
    names = {}
    for s in order:                       # number blocks in the order they are first reached
        names.setdefault(block[s], f"q{len(names)}")
    rep_of = {}
    for s in order:
        rep_of.setdefault(block[s], s)
    return {"kind": "DFA", "states": list(names.values()), "alphabet": alphabet[:],
            "start": names[block[dfa["start"]]],
            "accepts": [names[b] for b, s in rep_of.items() if s in finals],
            "trans": {(names[b], a): [names[block[trans[s, a][0]]]]
                      for b, s in rep_of.items() for a in alphabet}}


def _fits(machine: dict) -> dict:
    if len(machine["states"]) > MAX_STATES:
        raise FinalAnswer(f"That language needs {len(machine['states'])} states even after merging "
                          f"equivalent ones, more than the {MAX_STATES} that can be drawn clearly. "
                          "Try a smaller number.")
    return machine


def product_nfa(parts: List[dict]) -> dict:
    """NFA for the intersection of ε-free NFAs: run them side by side (product construction)."""
    alphabet = parts[0]["alphabet"]
    start = tuple(p["start"] for p in parts)
    names, queue = {start: "q0"}, deque([start])
    trans: Dict[Tuple[str, str], List[str]] = {}
    while queue:
        key = queue.popleft()
        for a in alphabet:
            options = [p["trans"].get((s, a), []) for p, s in zip(parts, key)]
            for combo in product(*options):
                if combo not in names:
                    if len(names) >= MAX_STATES:
                        raise FinalAnswer("too large")
                    names[combo] = f"q{len(names)}"
                    queue.append(combo)
                bucket = trans.setdefault((names[key], a), [])
                if names[combo] not in bucket:
                    bucket.append(names[combo])
    accepts = [n for key, n in names.items()
               if all(s in p["accepts"] for p, s in zip(parts, key))]
    return {"kind": "NFA", "states": list(names.values()), "alphabet": alphabet[:],
            "start": "q0", "accepts": accepts, "trans": trans}


def eps_union(parts: List[dict]) -> dict:
    """NFA for the union: a new start state with an ε-move into each part."""
    states, accepts = ["q0"], []
    trans: Dict[Tuple[str, str], List[str]] = {("q0", EPS): []}
    for part in parts:
        rename = {s: f"q{len(states) + i}" for i, s in enumerate(part["states"])}
        states += list(rename.values())
        trans["q0", EPS].append(rename[part["start"]])
        for (u, a), targets in part["trans"].items():
            trans[rename[u], a] = [rename[v] for v in targets]
        accepts += [rename[x] for x in part["accepts"]]
    return {"kind": "NFA", "states": states, "alphabet": parts[0]["alphabet"][:], "start": "q0",
            "accepts": accepts, "trans": trans}


def finite_language(words: List[str], text: str) -> Condition:
    """Exactly the given finite set of strings (a trie with a trap state)."""
    words = set(words)
    prefixes = {w[:i] for w in words for i in range(len(w) + 1)}

    def step(key, c):
        nxt = None if key is None else key + c
        return nxt if nxt in prefixes else None
    return Condition(text, "", step, lambda key: key in words)


POWER = r"((?:[A-Za-z0-9]\s*\^\s*\{?\s*n\s*\}?\s*){2,})"


def parse_finite(q: str):
    """Finite languages: a^n b^n with a bound on n, or an explicit set {ab, ba, aab}."""
    m = re.search(POWER, q)
    upper = re.search(r"\bn\s*(<=|≤|<)\s*(\d+)", q)
    if m and upper:
        hi = int(upper.group(2)) - (upper.group(1) == "<")
        lower = (re.search(r"\bn\s*(>=|≥|>)\s*(\d+)", q), re.search(r"(\d+)\s*(<=|≤|<)\s*n\b", q))
        lo = 0
        if lower[0]:
            lo = int(lower[0].group(2)) + (lower[0].group(1) == ">")
        elif lower[1]:
            lo = int(lower[1].group(1)) + (lower[1].group(2) == "<")
        symbols = re.findall(r"([A-Za-z0-9])\s*\^", m.group(1))
        if hi < lo:
            return empty_language(), "".join(symbols), m.span()
        if hi > 12:
            raise FinalAnswer("That bound gives a machine too large to draw clearly. Try n ≤ 12.")
        words = ["".join(x * n for x in symbols) for n in range(lo, hi + 1)]
        shown = ", ".join(w or EPS for w in words[:6]) + (", …" if len(words) > 6 else "")
        label = "".join(f"{x}ⁿ" for x in symbols)
        return (finite_language(words, f"w = {label} with {lo} ≤ n ≤ {hi}, i.e. w ∈ {{{shown}}} (finite, so regular)"),
                "".join(symbols), m.span())
    m = re.search(r"\{\s*((?:[A-Za-z0-9]+|ε)(?:\s*,\s*(?:[A-Za-z0-9]+|ε))+)\s*\}", q)
    if m:
        items = [t.strip() for t in m.group(1).split(",")]
        if any(len(t) > 1 for t in items):
            words = ["" if t == EPS else t for t in items]
            return (finite_language(words, f"w ∈ {{{', '.join(items)}}} (a finite language)"),
                    "".join(words), m.span())
    return None


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


def language_notes(machine: dict) -> List[str]:
    info = analyze_machine(machine)
    if info["shortest"] is None:
        return ["**Note:** no string satisfies these conditions together, so the language is "
                "**empty (∅)**: the DFA has no reachable accepting state."]
    live = info["reachable"]
    if live and all(s in machine["accepts"] for s in live):
        return ["**Note:** every string satisfies this, so **L = Σ\\***: all reachable states accept."]
    return []


def _from_regex(regex: str, q: str, alphabet: Optional[List[str]], wants_nfa: bool) -> dict:
    nfa = regex_to_nfa(regex)
    if alphabet:
        extra = [a for a in nfa["alphabet"] if a not in alphabet]
        if extra:
            raise NotUnderstood(f"Symbol(s) {', '.join(extra)} in {regex} are not in the alphabet "
                                f"{{{', '.join(alphabet)}}}.")
        nfa["alphabet"] = alphabet[:]
    sigma = ", ".join(nfa["alphabet"])
    tests = parse_test_strings(q, nfa["alphabet"], [m.span() for m in re.finditer(re.escape(regex), q)])
    eps_moves = sum(len(v) for (_, s), v in nfa["trans"].items() if s == EPS)
    if wants_nfa:
        steps_md = [f"**Language:** L({regex}) over {{{sigma}}}",
                    f"**Thompson's construction:** {len(nfa['states'])} states, {eps_moves} ε-moves, "
                    "one start state and one accepting state."]
        return _finish(nfa, f"ε-NFA for {regex}", steps_md, tests)
    dfa, _ = determinize(nfa)
    machine = tidy(_fits(_reduce(dfa)))
    steps_md = [f"**Language:** L({regex}) over {{{sigma}}}",
                f"**Method:** Thompson's construction gives a {len(nfa['states'])}-state ε-NFA; "
                f"subset construction gives a {len(dfa['states'])}-state DFA, and merging equivalent "
                f"states leaves this **{len(machine['states'])}-state DFA** (the fewest possible).",
                f"**Start:** {machine['start']}  ·  **Final:** {fmt_set(machine['accepts'])}"
                + ("  ·  **dead** is a trap state." if "dead" in machine["states"] else "")]
    return _finish(machine, f"DFA for {regex}", steps_md + language_notes(machine), tests)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def solve(question: str, current: Optional[dict] = None) -> dict:
    """Return a result dict, or raise NotUnderstood."""
    q = normalize(" ".join(question.strip().split()))
    if not q:
        raise NotUnderstood("Type a question first.")
    lower = q.lower()
    if re.search(r"\bminimi[sz]", lower) and not re.search(r"\b(?:construct|design|build|draw)\b", lower):
        raise FinalAnswer("DFA minimization is not part of this version of the simulator.")
    check_regular(q)
    alphabet = parse_alphabet(q)
    found = parse_conditions(q, alphabet)
    spans = [f[4] for f in found] + [m.span() for m in re.finditer(r"\{[^{}]*\}", q)]
    wants_nfa = bool(re.search(r"\b(?:ε|e|epsilon|lambda)?-?\s?nfa\b|non-?deterministic", lower)
                     and not re.search(r"\bdfa\b", lower))

    regex = find_regex(q)
    if regex and (not found or re.search(r"regular\s+expression|regex|\bR\.?E\.?|form|\bL\s*=", q, re.I)):
        return _from_regex(regex, q, alphabet, wants_nfa)

    finite = parse_finite(q)
    if finite:
        cond_f, chars_f, span_f = finite
        found = [(span_f[0], cond_f, None, chars_f, span_f)]
        spans.append(span_f)
        if alphabet and not set(chars_f) <= set(alphabet):
            alphabet = None

    if not found:
        for pattern, build in SPECIAL:
            sm = re.search(pattern, q, re.I)
            if sm:
                found = [(sm.start(), build(), None, "", sm.span())]
                spans.append(sm.span())
                break

    if found:
        chars = "".join(f[3] for f in found)
        if alphabet is None:
            if not chars and not re.search(r"\bbinary\b|\bbits?\b|\bdigits?\b", q, re.I):
                alphabet = ["a", "b"]
            elif set(chars) <= {"0", "1"}:
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
        connectors = ["or" if re.search(r"\bor\b", q[a[4][1]:b[4][0]], re.I) else "and"
                      for a, b in zip(found, found[1:])]
        cond = combine_mixed([f[1] for f in found], connectors)
        tests = parse_test_strings(q, alphabet, spans)
        language = f"L = {{ w ∈ {{{', '.join(alphabet)}}}* | {cond.text} }}"

        kinds = [f[2] for f in found]
        if wants_nfa and len(found) > 1 and all(kinds):
            words = [re.sub(r"[^A-Za-z0-9]", "", f[3]) for f in found]
            machine = idea = None
            if all(c == "or" for c in connectors) and all(k in ("contains", "ends", "starts") for k in kinds):
                machine, idea = union_nfa(kinds, words, alphabet)
            else:
                groups, current_group = [], [0]          # AND binds tighter than OR
                for i, conn in enumerate(connectors, start=1):
                    if conn == "or":
                        groups.append(current_group)
                        current_group = [i]
                    else:
                        current_group.append(i)
                groups.append(current_group)
                try:
                    parts = []
                    for group in groups:
                        nfas = [classic_nfa(kinds[i], words[i], alphabet) for i in group]
                        parts.append(nfas[0] if len(nfas) == 1 else product_nfa(nfas))
                    machine = parts[0] if len(parts) == 1 else eps_union(parts)
                    if len(machine["states"]) > MAX_STATES:
                        machine = None
                    idea = ("product construction: one small NFA per condition runs side by side. "
                            "Each state stands for one state of every small NFA, and it accepts only "
                            "when all of them accept (intersection)."
                            + (" The OR parts are joined by a new start state with ε-moves (union)."
                               if len(parts) > 1 else ""))
                except FinalAnswer:
                    machine = None
            if machine:
                steps_md = [f"**Language:** {language}", f"**Idea:** {idea}",
                            f"**NFA:** {len(machine['states'])} states, start {machine['start']}, "
                            f"final {fmt_set(machine['accepts'])}."]
                return _finish(machine, f"NFA: {cond.text}", steps_md, tests)

        if wants_nfa and len(found) == 1 and found[0][2]:
            machine = classic_nfa(found[0][2], re.sub(r"[^A-Za-z0-9]", "", found[0][3]), alphabet)
            idea = {"starts": "read the prefix first, then loop on everything"}.get(
                found[0][2], "the NFA guesses where the pattern occurs; q0 loops on every symbol")
            if found[0][2].startswith("kth_end"):
                idea = ("q0 loops on every symbol and guesses which symbol is the chosen one; "
                        "after it, exactly the right number of symbols must follow. The equivalent "
                        "DFA needs exponentially more states, the classic NFA-vs-DFA example")
            steps_md = [
                f"**Language:** {language}",
                f"**Idea:** {idea}.",
                f"**NFA:** {len(machine['states'])} states, start q0, final {fmt_set(machine['accepts'])}.",
            ]
            return _finish(machine, f"NFA: {cond.text}", steps_md, tests)

        try:
            raw = _explore(alphabet, cond.start, cond.step, cond.accept)
            reduced = _fits(_reduce(raw))
        except FinalAnswer as exc:
            kth = [f[2] for f in found if f[2] and f[2].startswith("kth_end")]
            if kth and len(found) == 1:
                k = int(kth[0].split(":")[1])
                raise FinalAnswer(f"{exc} The DFA needs about 2^{k} states, but an NFA needs only "
                                  f"{k + 1}: ask for an NFA instead (e.g. \"NFA for …\").") from None
            raise
        machine = tidy(reduced)
        merged = (f"; {len(raw['states'])} states were built and equivalent ones merged"
                  if len(raw["states"]) > len(machine["states"]) else "")
        steps_md = [
            f"**Language:** {language}",
            f"**Construction:** each state remembers just enough of the input to decide "
            f"*{cond.text}*{merged}, giving **{len(machine['states'])} states** "
            "(the fewest possible for this language).",
            f"**Start:** {machine['start']}  ·  **Final:** {fmt_set(machine['accepts'])}"
            + ("  ·  **dead** is a trap state." if "dead" in machine["states"] else ""),
        ]
        if wants_nfa:
            steps_md.append("This condition has no simpler nondeterministic form here; every DFA is "
                            "also an NFA, so this machine answers the NFA question too.")
        steps_md += language_notes(machine)
        return _finish(machine, f"DFA: {cond.text}", steps_md, tests)

    # ---- Questions about the machine that is already loaded ---------------- #
    if current is None:
        if re.search(r"\b(?:is|are|check|test)\b", lower) and parse_test_strings(q, None, spans):
            raise NotUnderstood("Load or describe a machine first, then ask which strings it accepts.")
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
