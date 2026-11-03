"""DFA/NFA Explorer — a Streamlit workbench for DFA and epsilon-NFA exploration."""
from pathlib import Path
import hashlib
import json

import pandas as pd
import streamlit as st

from automata import (
    EPS, PRESETS, DEFAULT_PRESET, analyze_machine, build_machine,
    export_machine, fmt_set, import_machine,
    normalize_input, simulate, verdict,
)

st.set_page_config(page_title="DFA/NFA Explorer", page_icon=":material/hub:", layout="wide")

# Inline CCv2 component: source is kept separately for readability, passed as
# trusted literal content. User strings only travel through the data channel.
_ROOT = Path(__file__).parent
st.html("<style>" + (_ROOT / "mobile.css").read_text(encoding="utf-8") + "</style>")
_VISUALIZER = st.components.v2.component(
    "automata_player",
    html='<div class="automata-player"></div>\n',
    css=(_ROOT / "player.css").read_text(encoding="utf-8"),
    js=(_ROOT / "player.js").read_text(encoding="utf-8"),
)

if "spec" not in st.session_state:
    st.session_state.spec = PRESETS[DEFAULT_PRESET]
    st.session_state.version = 0


def load_spec(spec):
    st.session_state.spec = spec
    st.session_state.version += 1


def load_preset():
    load_spec(PRESETS[st.session_state.preset])


with st.sidebar:
    st.title("DFA/NFA Explorer", icon=":material/hub:")
    st.caption("A playground for finite state machines")
    st.selectbox("Example machine", list(PRESETS), key="preset", on_change=load_preset)
    st.button("Reload example", icon=":material/restart_alt:", on_click=load_preset, width="stretch")
    spec = st.session_state.spec
    version = st.session_state.version
    st.caption(spec["blurb"])
    kind = st.segmented_control("Machine type", ["DFA", "NFA"],
                                default=spec["kind"], required=True, key=f"kind_{version}")
    states_txt = st.text_input("States", spec["states"], key=f"states_{version}")
    alpha_txt = st.text_input("Alphabet", spec["alphabet"], key=f"alpha_{version}",
                             help="Comma-separated, single-character symbols. ε is reserved.")
    start_col, final_col = st.columns(2)
    start_txt = start_col.text_input("Start state", spec["start"], key=f"start_{version}")
    accepts_txt = final_col.text_input("Accepting states", spec["accepts"], key=f"accepts_{version}")
    st.caption("Use commas between state names. Leave accepting states blank for the empty language.")
    st.subheader("Transitions")
    seed = pd.DataFrame(spec["transitions"], columns=["From", "Symbol", "To"])
    edited = st.data_editor(seed, num_rows="dynamic", hide_index=True, width="stretch",
                            key=f"trans_{version}", column_config={
        "From": st.column_config.TextColumn(width="small"),
        "Symbol": st.column_config.TextColumn(width="small"),
        "To": st.column_config.TextColumn(width="small"),
    })
    st.caption("NFA: separate targets with commas. ε, eps, epsilon, @ or <eps> means an empty move.")
    with st.expander("Import machine", icon=":material/upload:"):
        uploaded = st.file_uploader("Automaton JSON", type="json", max_upload_size=1)
        if st.button("Load JSON", disabled=uploaded is None):
            try:
                imported = import_machine(uploaded.getvalue().decode("utf-8"))
            except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                st.error(str(exc))
            else:
                load_spec(imported)
                st.rerun()

st.title("Watch a machine think.")
st.caption("Build a DFA or ε-NFA. Follow every symbol, explore the live state set, and see why a string accepts.")

machine, errors, warnings = build_machine(kind, states_txt, alpha_txt, start_txt, accepts_txt, edited)
if errors:
    st.error("Fix the machine definition to start exploring.")
    for message in errors:
        st.error(message)
    st.stop()

with st.container(horizontal=True):
    st.badge(kind, color="violet", icon=":material/hub:")
    st.badge(f"{len(machine['states'])} states", color="gray")
    st.badge(f"{sum(len(t) for t in machine['trans'].values())} transitions", color="gray")
    st.badge(f"Σ = {fmt_set(machine['alphabet'])}", color="blue")

for warning in warnings:
    st.warning(warning)

simulate_tab, test_tab, learn_tab = st.tabs(
    ["Simulate", "Test strings", "Machine insights"])

with simulate_tab:
    text = normalize_input(st.text_input("Input string", spec.get("sample", ""),
                                         key=f"input_{version}", max_chars=2000,
                                         help="Leave blank or enter ε for the empty string. All other characters are literal."))
    bad = sorted(set(text) - set(machine["alphabet"]))
    if bad:
        st.warning("Outside the alphabet: " + ", ".join(repr(ch) for ch in bad)
                   + ". The run rejects at the first such symbol it reaches.")
    steps, accepted, final, stuck = simulate(machine, text)
    _, explanation = verdict(machine, steps, accepted, final, stuck)
    payload = {
        "machine": {k: machine[k] for k in ("kind", "states", "alphabet", "start", "accepts")},
        "edges": [[u, a, v] for (u, a), targets in machine["trans"].items() for v in targets],
        "steps": [{k: sorted(v) if isinstance(v, (set, frozenset)) else v
                   for k, v in step.items()} for step in steps],
        "text": text, "accepted": accepted, "explanation": explanation,
    }
    # Stable across unrelated reruns; input or definition edits start a fresh run.
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    _VISUALIZER(data=payload, key=f"run_{identity}", height="content")
    trace = pd.DataFrame([
        {"Step": i, "Symbol": s["sym"] or EPS,
         "Before": fmt_set(s["before"]), "After": fmt_set(s["after"]),
         "Explanation": s["note"]} for i, s in enumerate(steps)
    ])
    with st.container(horizontal=True):
        st.download_button("Export machine", export_machine(machine), "automaton.json",
                           "application/json", icon=":material/download:")
        st.download_button("Download trace", trace.to_csv(index=False).encode("utf-8"),
                           "trace.csv", "text/csv", icon=":material/table_chart:")

with test_tab:
    st.subheader("Try a whole language sample")
    st.caption("One string per line; ε represents empty input. Blank lines are ignored. Spaces are literal symbols.")
    raw = st.text_area("Test strings", "\n".join(spec.get("batch", [EPS])),
                       height=160, key=f"batch_{version}", max_chars=20000)
    results = []
    for candidate in raw.splitlines():
        if candidate == "":
            continue
        probe = normalize_input(candidate)
        run, ok, end, died = simulate(machine, probe)
        results.append({"String": probe or EPS, "Accepted": ok, "Final states": fmt_set(end),
                        "Reason": verdict(machine, run, ok, end, died)[1]})
    if results:
        st.caption(f"{sum(row['Accepted'] for row in results)} / {len(results)} strings accepted")
        st.dataframe(pd.DataFrame(results), hide_index=True, width="stretch")
        st.download_button("Download results", pd.DataFrame(results).to_csv(index=False).encode("utf-8"),
                           "batch-results.csv", "text/csv")
    else:
        st.caption("Enter strings to test. Use ε to test the empty string.")

with learn_tab:
    analysis = analyze_machine(machine)
    st.subheader("Understand this automaton")
    a, b, c = st.columns(3)
    a.metric("Reachable states", f"{len(analysis['reachable'])} / {len(machine['states'])}")
    b.metric("Dead states", len(analysis["dead"]))
    c.metric("Shortest accepted string", "None" if analysis["shortest"] is None else analysis["shortest"] or EPS)
    if analysis["shortest"] is None:
        st.info("The language is empty: no accepting state is reachable from the start.")
    st.markdown(f"**Unreachable:** {fmt_set(analysis['unreachable'])}  \n"
                f"**Cannot reach acceptance:** {fmt_set(analysis['dead'])}  \n"
                f"**Transition function:** {'complete' if analysis['complete'] else 'partial'}")
    st.latex(r"M = (Q, \Sigma, \delta, q_0, F)")
    st.markdown("**Q** is the set of states, **Σ** the alphabet, **δ** the transition function, "
                "**q₀** the start state, and **F** the set of accepting states.")
    st.markdown("A **DFA** follows one state per symbol. An **NFA** tracks every possible live state; "
                "acceptance requires at least one accepting state **after the entire string is read**. "
                "An **ε-move** consumes no input, so ε-closure is applied before the first symbol and after every move.")
    st.caption("The visual shows state sets, not counts of distinct paths. Paths that reach the same state merge.")
    matrix = []
    for state in machine["states"]:
        row = {"State": state, "Start": state == machine["start"], "Accepting": state in machine["accepts"]}
        for symbol in machine["alphabet"] + ([EPS] if any(a == EPS for _, a in machine["trans"]) else []):
            row[symbol] = fmt_set(machine["trans"].get((state, symbol), []), single=kind == "DFA")
        matrix.append(row)
    st.dataframe(pd.DataFrame(matrix), hide_index=True, width="stretch")
