"""Validation, simulation and transformations for character-based finite automata."""

from __future__ import annotations

from collections import deque
import json
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

import pandas as pd

EPS = "ε"
EPS_INPUTS = {"ε", "eps", "epsilon", "@", "<eps>"}


def normalize_input(text: str) -> str:
    """Only a standalone ε denotes empty input; all other characters are literal."""
    return "" if text == EPS else text

# --------------------------------------------------------------------------- #
# Presets
# --------------------------------------------------------------------------- #


def _preset(kind, states, alphabet, start, accepts, transitions, sample, blurb, batch):
    return {
        "kind": kind,
        "states": states,
        "alphabet": alphabet,
        "start": start,
        "accepts": accepts,
        "transitions": transitions,
        "sample": sample,
        "blurb": blurb,
        "batch": batch,
    }


PRESETS: Dict[str, dict] = {
    'Ends with "01"': _preset(
        "DFA", "q0, q1, q2", "0, 1", "q0", "q2",
        [("q0", "0", "q1"), ("q0", "1", "q0"),
         ("q1", "0", "q1"), ("q1", "1", "q2"),
         ("q2", "0", "q1"), ("q2", "1", "q0")],
        "1101",
        "The classic three-state DFA that remembers the last two symbols.",
        ["0110", "101", "00", "1101", "1"],
    ),
    "Even number of a's": _preset(
        "DFA", "even, odd", "a, b", "even", "even",
        [("even", "a", "odd"), ("odd", "a", "even"),
         ("even", "b", "even"), ("odd", "b", "odd")],
        "abaa",
        "Parity counting: two states, b-loops on both.",
        ["abaa", "a", "aa", "bbb", "ε"],
    ),
    "Binary number divisible by 3": _preset(
        "DFA", "r0, r1, r2", "0, 1", "r0", "r0",
        [("r0", "0", "r0"), ("r0", "1", "r1"),
         ("r1", "0", "r2"), ("r1", "1", "r0"),
         ("r2", "0", "r1"), ("r2", "1", "r2")],
        "1001",
        "States track the value read so far modulo 3.",
        ["1001", "11", "111", "0", "1010"],
    ),
    "Starts with 10 (dead state)": _preset(
        "DFA", "q0, q1, q2, dead", "0, 1", "q0", "q2",
        [("q0", "1", "q1"), ("q0", "0", "dead"),
         ("q1", "0", "q2"), ("q1", "1", "dead"),
         ("q2", "0", "q2"), ("q2", "1", "q2"),
         ("dead", "0", "dead"), ("dead", "1", "dead")],
        "10001",
        "Shows how a trap state soaks up the rejected strings.",
        ["10001", "10", "01", "110", "0"],
    ),
    'Contains "ab"': _preset(
        "NFA", "s0, s1, s2", "a, b", "s0", "s2",
        [("s0", "a", "s0"), ("s0", "b", "s0"), ("s0", "a", "s1"),
         ("s1", "b", "s2"), ("s2", "a", "s2"), ("s2", "b", "s2")],
        "baab",
        "Nondeterminism: s0 guesses the moment the pattern starts.",
        ["baab", "bbb", "ab", "a", "ba"],
    ),
    "a*b with ε-transitions": _preset(
        "NFA", "p0, p1, p2", "a, b", "p0", "p2",
        [("p0", "ε", "p1"), ("p0", "a", "p0"), ("p1", "b", "p2")],
        "aab",
        "An ε-move guesses when the a-prefix ends; exactly one final b is required.",
        ["aab", "b", "ab", "aa", "ba"],
    ),
}

DEFAULT_PRESET = 'Ends with "01"'

# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #


def split_items(text: str) -> List[str]:
    """Split a comma/whitespace separated list, keeping order and uniqueness."""
    out: List[str] = []
    for chunk in str(text or "").replace(",", " ").split():
        if chunk not in out:
            out.append(chunk)
    return out


def cell(value) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def fmt_set(states: Sequence[str], single: bool = False) -> str:
    ordered = sorted(states)
    if not ordered:
        return "∅"
    if single and len(ordered) == 1:
        return ordered[0]
    return "{" + ", ".join(ordered) + "}"


def eps_closure(nodes: Sequence[str], trans: Dict[Tuple[str, str], List[str]]):
    """Return the ε-closure of ``nodes`` plus the ε-edges used to get there."""
    seen: Set[str] = set(nodes)
    edges: Set[Tuple[str, str, str]] = set()
    stack = list(nodes)
    while stack:
        u = stack.pop()
        for v in trans.get((u, EPS), []):
            edges.add((u, EPS, v))
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return frozenset(seen), edges


def build_machine(kind: str, states_txt: str, alpha_txt: str, start_txt: str,
                  accepts_txt: str, rows: pd.DataFrame):
    """Validate the raw form input and return (machine, errors, warnings)."""
    errors: List[str] = []
    if kind not in ("DFA", "NFA"):
        errors.append("Machine type must be DFA or NFA.")
    warnings: List[str] = []

    states = split_items(states_txt)
    if not states:
        errors.append("Define at least one state.")

    alphabet = split_items(alpha_txt)
    if not alphabet:
        errors.append("The alphabet must contain at least one symbol.")
    for sym in list(alphabet):
        if sym.lower() in EPS_INPUTS:
            errors.append(f"“{sym}” is reserved for ε-transitions and cannot be an alphabet symbol.")
            alphabet.remove(sym)
        elif len(sym) != 1:
            errors.append(f"Alphabet symbol “{sym}” is not a single character.")

    start = str(start_txt or "").strip()
    if not start:
        errors.append("Pick a start state.")
    elif start not in states:
        errors.append(f"Start state “{start}” is not in the state list.")

    accepts = split_items(accepts_txt)
    for a in accepts:
        if a not in states:
            errors.append(f"Accepting state “{a}” is not in the state list.")

    trans: Dict[Tuple[str, str], List[str]] = {}
    for idx, (_, row) in enumerate(rows.iterrows()):
        src = cell(row.get("From"))
        sym_raw = cell(row.get("Symbol"))
        dst_raw = cell(row.get("To"))
        if not (src or sym_raw or dst_raw):
            continue
        line = f"row {int(idx) + 1}"
        if not src or not sym_raw or not dst_raw:
            errors.append(f"Transition {line} is incomplete — fill From, Symbol and To.")
            continue
        symbol = EPS if sym_raw.lower() in EPS_INPUTS else sym_raw
        if symbol != EPS and len(symbol) != 1:
            errors.append(f"Transition {line}: symbol “{symbol}” is not a single character.")
            continue
        if symbol != EPS and symbol not in alphabet:
            errors.append(f"Transition {line}: symbol “{symbol}” is not in the alphabet.")
            continue
        if src not in states:
            errors.append(f"Transition {line}: unknown source state “{src}”.")
            continue
        targets = split_items(dst_raw.replace(";", " "))
        if not targets:
            errors.append(f"Transition {line}: specify at least one target state.")
        for target in targets:
            if target not in states:
                errors.append(f"Transition {line}: unknown target state “{target}”.")
                continue
            bucket = trans.setdefault((src, symbol), [])
            if target not in bucket:
                bucket.append(target)

    if kind == "DFA":
        for (src, symbol) in trans:
            if symbol == EPS:
                errors.append("A DFA cannot use ε-transitions — switch the type to NFA.")
                break
        for (src, symbol), targets in trans.items():
            if len(targets) > 1:
                errors.append(
                    f"Nondeterministic pair ({src}, {symbol}) → {fmt_set(targets)} — "
                    "a DFA allows only one target."
                )
                break

    if kind == "DFA":
        missing = [
            f"({u}, {s})" for u in states for s in alphabet
            if (u, s) not in trans
        ]
        if missing and not errors:
            shown = ", ".join(missing[:6]) + (" …" if len(missing) > 6 else "")
            warnings.append(
                f"Partial DFA: no transition defined for {shown}. "
                "The run rejects as soon as it gets stuck."
            )

    machine = {
        "kind": kind,
        "states": states,
        "alphabet": alphabet,
        "start": start,
        "accepts": accepts,
        "trans": trans,
        "rows": rows,
    }

    if not errors and states and start:
        reachable = _reachable(start, trans)
        unreachable = [s for s in states if s not in reachable]
        if unreachable:
            warnings.append(
                "Unreachable state(s): " + ", ".join(unreachable)
                + " — nothing ever enters them."
            )

    return machine, errors, warnings


def _reachable(start: str, trans: Dict[Tuple[str, str], List[str]]) -> Set[str]:
    seen = {start}
    stack = [start]
    while stack:
        u = stack.pop()
        for (src, _sym), targets in trans.items():
            if src != u:
                continue
            for v in targets:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
    return seen


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #


def simulate(machine: dict, text: str):
    """Run ``text`` on the machine and return the full step trace."""
    text = normalize_input(text)
    trans = machine["trans"]
    is_dfa = machine["kind"] == "DFA"
    start = machine["start"]

    steps: List[dict] = []
    if is_dfa:
        current: FrozenSet[str] = frozenset({start})
        closure_edges: Set[Tuple[str, str, str]] = set()
        note = f"start in {start}"
    else:
        current, closure_edges = eps_closure([start], trans)
        note = f"ε-closure({start}) = {fmt_set(current)}"

    steps.append({
        "sym": None, "before": frozenset(), "moved": frozenset(),
        "after": current, "taken": [], "eps": closure_edges,
        "note": note, "stuck": False,
    })

    stuck_at: Optional[int] = None
    for idx, ch in enumerate(text):
        before = current
        moved: Set[str] = set()
        taken: List[Tuple[str, str, str]] = []
        for state in sorted(before):
            for target in trans.get((state, ch), []):
                moved.add(target)
                if (state, ch, target) not in taken:
                    taken.append((state, ch, target))

        if not moved:
            steps.append({
                "sym": ch, "before": before, "moved": frozenset(),
                "after": frozenset(), "taken": [], "eps": set(),
                "note": f"no transition on “{ch}” from {fmt_set(before)} — the run dies here",
                "stuck": True,
            })
            stuck_at = idx
            current = frozenset()
            break

        if is_dfa:
            after: FrozenSet[str] = frozenset(moved)
            eps_edges: Set[Tuple[str, str, str]] = set()
        else:
            after, eps_edges = eps_closure(moved, trans)

        if is_dfa:
            note = f"δ({fmt_set(before, True)}, {ch}) = {fmt_set(after, True)}"
        else:
            note = f"δ({fmt_set(before)}, {ch}) = {fmt_set(moved)}"
            if eps_edges or after != frozenset(moved):
                note += f"  →  ε-closure {fmt_set(after)}"

        steps.append({
            "sym": ch, "before": before, "moved": frozenset(moved),
            "after": after, "taken": taken, "eps": eps_edges,
            "note": note, "stuck": False,
        })
        current = after

    accepted = bool(current & set(machine["accepts"]))
    return steps, accepted, current, stuck_at


def verdict(machine: dict, steps: List[dict], accepted: bool,
            final: FrozenSet[str], stuck_at: Optional[int]) -> Tuple[str, str]:
    """Return (status, explanation) for the finished run."""
    is_dfa = machine["kind"] == "DFA"
    shown = fmt_set(final, single=is_dfa)
    if stuck_at is not None:
        step = steps[-1]
        return (
            "rejected",
            f"The run died at position {stuck_at + 1}: there is no transition out of "
            f"{fmt_set(step['before'], single=is_dfa)} on “{step['sym']}”.",
        )
    if accepted:
        return (
            "accepted",
            f"The whole input was read. Final states: {shown}; at least one is accepting.",
        )
    if not final:
        return ("rejected", "No states are alive, so nothing can accept.")
    accepting = ""
    return (
        "rejected",
        f"The whole input was read, but the machine ends in {shown}{accepting} — "
        "not an accepting state.",
    )


def machine_from_spec(spec: dict):
    rows = pd.DataFrame(spec["transitions"], columns=["From", "Symbol", "To"])
    return build_machine(spec["kind"], spec["states"], spec["alphabet"],
                         spec["start"], spec["accepts"], rows)


def machine_to_spec(machine: dict, sample: str = "") -> dict:
    return _preset(
        machine["kind"], ", ".join(machine["states"]),
        ", ".join(machine["alphabet"]), machine["start"],
        ", ".join(machine["accepts"]),
        [(src, sym, ", ".join(targets))
         for (src, sym), targets in machine["trans"].items()],
        sample, "Custom automaton. Edit its definition below.", [sample, EPS],
    )


def export_machine(machine: dict) -> str:
    """Portable schema independent of pandas and editor state."""
    return json.dumps({
        "version": 1, "kind": machine["kind"], "states": machine["states"],
        "alphabet": machine["alphabet"], "start": machine["start"],
        "accepts": machine["accepts"],
        "transitions": [{"from": src, "symbol": sym, "to": targets}
                        for (src, sym), targets in machine["trans"].items()],
    }, indent=2, ensure_ascii=False)


def import_machine(raw: str) -> dict:
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Expected an automaton JSON object with version 1.")
    for key in ("states", "alphabet", "accepts"):
        values = data.get(key)
        if not isinstance(values, list) or not all(isinstance(s, str) for s in values):
            raise ValueError(f"{key} must be a list of strings.")
        if any(not s or split_items(s) != [s] for s in values):
            raise ValueError(f"{key} entries must be nonempty and contain no commas or whitespace.")
    if not isinstance(data.get("start"), str):
        raise ValueError("start must be a state name.")
    transitions = data.get("transitions")
    if not isinstance(transitions, list):
        raise ValueError("transitions must be a list.")
    rows = []
    for row in transitions:
        if (not isinstance(row, dict) or not isinstance(row.get("from"), str)
                or not isinstance(row.get("symbol"), str)
                or not isinstance(row.get("to"), list) or not row["to"]
                or not all(isinstance(s, str) and s in data["states"] for s in row["to"])):
            raise ValueError("Each transition needs from, symbol, and a nonempty to list of state names.")
        rows.append((row["from"], row["symbol"], ", ".join(row["to"])))
    spec = _preset(data.get("kind"), ", ".join(data["states"]),
                   ", ".join(data["alphabet"]), data["start"],
                   ", ".join(data["accepts"]), rows, "", "Imported automaton.", [EPS])
    _, errors, _ = machine_from_spec(spec)
    if errors:
        raise ValueError(" ".join(errors))
    return spec


def determinize(machine: dict, max_states: int = 128):
    """Reachable subset construction, including an explicit empty-set trap.

    Return a total DFA and a mapping from its names to original state subsets.
    Bound the exponential construction before adding any state beyond the limit.
    """
    initial, _ = eps_closure([machine["start"]], machine["trans"])
    subsets = {initial: "D0"}
    queue = deque([initial])
    transitions = {}
    accepts = []
    while queue:
        subset = queue.popleft()
        name = subsets[subset]
        if subset & set(machine["accepts"]):
            accepts.append(name)
        for symbol in machine["alphabet"]:
            moved = {v for u in subset for v in machine["trans"].get((u, symbol), [])}
            target, _ = eps_closure(moved, machine["trans"])
            if target not in subsets:
                if len(subsets) >= max_states:
                    raise ValueError(f"Construction exceeds {max_states} states. Simplify the machine first.")
                subsets[target] = f"D{len(subsets)}"
                queue.append(target)
            transitions[name, symbol] = [subsets[target]]
    result = {"kind": "DFA", "states": list(subsets.values()),
              "alphabet": machine["alphabet"][:], "start": "D0",
              "accepts": accepts, "trans": transitions}
    return result, {name: subset for subset, name in subsets.items()}


def minimize_dfa(machine: dict):
    """Complete partial DFAs, remove unreachable states, and refine partitions."""
    if machine["kind"] != "DFA":
        raise ValueError("Convert the NFA to a DFA before minimizing it.")
    dfa, original = determinize(machine)
    finals = set(dfa["accepts"])
    partitions = [p for p in (finals, set(dfa["states"]) - finals) if p]
    while True:
        block_of = {s: i for i, block in enumerate(partitions) for s in block}
        refined = []
        for block in partitions:
            groups = {}
            for state in sorted(block):
                signature = tuple(block_of[dfa["trans"][state, a][0]] for a in dfa["alphabet"])
                groups.setdefault(signature, set()).add(state)
            refined.extend(groups.values())
        if len(refined) == len(partitions):
            break
        partitions = refined
    # Stable names: the start block is always M0.
    partitions.sort(key=lambda block: (dfa["start"] not in block, min(block)))
    names = {s: f"M{i}" for i, block in enumerate(partitions) for s in block}
    result = {"kind": "DFA", "states": [f"M{i}" for i in range(len(partitions))],
              "alphabet": dfa["alphabet"][:], "start": "M0",
              "accepts": [f"M{i}" for i, b in enumerate(partitions) if b & finals],
              "trans": {(f"M{i}", a): [names[dfa["trans"][next(iter(b)), a][0]]]
                        for i, b in enumerate(partitions) for a in dfa["alphabet"]}}
    mapping = {f"M{i}": frozenset(s for q in b for s in original[q])
               for i, b in enumerate(partitions)}
    return result, mapping


def analyze_machine(machine: dict) -> dict:
    """Graph diagnostics and a shortest accepted word (ε-edges cost zero)."""
    trans = machine["trans"]
    reachable = _reachable(machine["start"], trans)
    productive = set(machine["accepts"])
    while True:
        expanded = productive | {src for (src, _), targets in trans.items()
                                  if productive.intersection(targets)}
        if expanded == productive:
            break
        productive = expanded
    # 0-1 BFS on individual NFA states avoids exponential subset exploration.
    distances = {machine["start"]: 0}
    words = {machine["start"]: ""}
    queue = deque([machine["start"]])
    while queue:
        src = queue.popleft()
        for (u, symbol), targets in trans.items():
            if u != src:
                continue
            cost = int(symbol != EPS)
            for dst in targets:
                distance = distances[src] + cost
                if distance < distances.get(dst, float("inf")):
                    distances[dst] = distance
                    words[dst] = words[src] + (symbol if cost else "")
                    (queue.append if cost else queue.appendleft)(dst)
    candidates = [words[s] for s in machine["accepts"] if s in words]
    return {"reachable": reachable,
            "unreachable": set(machine["states"]) - reachable,
            "dead": set(machine["states"]) - productive,
            "shortest": min(candidates, key=lambda w: (len(w), w)) if candidates else None,
            "complete": all((s, a) in trans for s in machine["states"] for a in machine["alphabet"])}


