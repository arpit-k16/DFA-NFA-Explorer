"""Computation tree for DFA/NFA runs: every branch the machine explores.

Unlike the state-set view, branches are never merged, so the tree shows each
individual computation path, where it dies, and which paths accept.
"""
from __future__ import annotations

from typing import Dict, List

from automata import EPS, normalize_input

MAX_NODES = 400


def build_tree(machine: dict, text: str, max_nodes: int = MAX_NODES) -> dict:
    """Return {"nodes": [...], "truncated": bool, "summary": {...}}.

    Each node: id, parent, state, pos (symbols consumed), via (symbol, ε or None),
    status: "accept" | "reject" | "dead" | "loop" | "cut" | "inner",
    and on_accept_path: True for nodes on some accepting branch.
    """
    text = normalize_input(text)
    trans = machine["trans"]
    accepts = set(machine["accepts"])
    nodes: List[dict] = []
    truncated = False

    def add(state, pos, via, parent):
        nodes.append({"id": len(nodes), "parent": parent, "state": state, "pos": pos,
                      "via": via, "status": "inner", "on_accept_path": False})
        return len(nodes) - 1

    root = add(machine["start"], 0, None, None)
    # Stack entries: node id, set of states already on this branch's current ε-run.
    stack = [(root, frozenset({machine["start"]}))]
    while stack:
        node_id, eps_seen = stack.pop()
        node = nodes[node_id]
        state, pos = node["state"], node["pos"]
        children = []
        for target in trans.get((state, EPS), []):
            if target in eps_seen:
                continue  # ε-cycle: following it again adds nothing new
            children.append((target, pos, EPS, eps_seen | {target}))
        if pos < len(text):
            for target in trans.get((state, text[pos]), []):
                children.append((target, pos + 1, text[pos], frozenset({target})))
        if not children:
            if pos == len(text):
                node["status"] = "accept" if state in accepts else "reject"
            else:
                node["status"] = "dead"
            continue
        if len(nodes) + len(children) > max_nodes:
            node["status"] = "cut"
            truncated = True
            continue
        for target, npos, via, seen in reversed(children):
            stack.append((add(target, npos, via, node_id), seen))
        # Keep children in natural order for layout (DFS pops reversed list).

    # A finished path that consumed all input in an accepting state also accepts
    # even if it still has outgoing ε-moves.
    for node in nodes:
        if node["status"] == "inner" and node["pos"] == len(text) and node["state"] in accepts:
            node["status"] = "accept"

    by_id: Dict[int, dict] = {n["id"]: n for n in nodes}
    for node in nodes:
        if node["status"] == "accept":
            cur = node
            while cur is not None and not cur["on_accept_path"]:
                cur["on_accept_path"] = True
                cur = by_id.get(cur["parent"]) if cur["parent"] is not None else None

    leaves = [n for n in nodes if n["status"] != "inner"]
    summary = {
        "nodes": len(nodes),
        "branches": len(leaves),
        "accepting": sum(n["status"] == "accept" for n in leaves),
        "rejecting": sum(n["status"] == "reject" for n in leaves),
        "dead": sum(n["status"] == "dead" for n in leaves),
        "cut": sum(n["status"] == "cut" for n in leaves),
    }
    return {"nodes": nodes, "truncated": truncated, "summary": summary,
            "accepted": summary["accepting"] > 0, "text": text}


def accepting_path(tree: dict) -> List[dict]:
    """One root-to-leaf accepting branch (the first found), or []."""
    nodes = {n["id"]: n for n in tree["nodes"]}
    leaf = next((n for n in tree["nodes"] if n["status"] == "accept"), None)
    path = []
    while leaf is not None:
        path.append(leaf)
        leaf = nodes.get(leaf["parent"]) if leaf["parent"] is not None else None
    return path[::-1]


def describe_path(path: List[dict]) -> str:
    if not path:
        return ""
    out = path[0]["state"]
    for node in path[1:]:
        out += f" --{node['via']}--> {node['state']}"
    return out
