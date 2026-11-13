# DFA/NFA String Processing Visualizer — Group [Group ID]

CSET302 Automata Theory and Computability · Simulator Project, Topic 7 · Milestone-II

## Overview

A browser-based simulator that animates how a DFA, NFA or ε-NFA processes an
input string, symbol by symbol, and explains why the string is accepted or
rejected. A separate computation-tree view shows every nondeterministic branch,
where it gets stuck, and which branch accepts.

## Supported features

- Define a DFA or NFA/ε-NFA in a transition-table editor (Q, Σ, q₀, F, δ), or load
  one of six examples.
- Animated simulation: input tape, live state set, taken transitions, ε-closures,
  play / pause / step / scrub / speed, keyboard shortcuts, step-by-step trace.
- Acceptance/rejection verdict with a plain-language reason.
- **Computation tree** tab: every branch of the run, marked ✗ stuck,
  ✗ not final or ✓ accept, with the accepting path highlighted.
- **Regular expression → ε-NFA** (Thompson's construction): `(a|b)*ab`,
  `(a+b)*abb`, `a?b`, `ε`.
- **Ask a question** box: e.g. *"DFA over {0,1} for strings ending with 01 and
  check 1101, 0110"*, *"Strings that do not contain consecutive 11"*, *"Strings that
  start and end with the same symbol"*, *"NFA where the third symbol from the end is 1"*,
  *"Every a is followed by b"*, *"DFA for (a+b)*abb"*, *"n_a(w) mod 3 = 1"*,
  *"Is 1101 accepted?"*, *"Convert this NFA to a DFA"*. Requests for non-regular languages
  (palindromes, aⁿbⁿ, equal numbers of a's and b's, ww …) are explained with a
  pumping-lemma sketch instead of producing a wrong machine.
- Test many strings at once (CSV download).
- NFA → DFA conversion (subset construction).
- Machine insights: reachable, unreachable and dead states, shortest accepted
  string, transition matrix.
- Import/export machines as JSON; download the diagram as SVG and the trace as CSV.
- Optional Google Gemini fallback for questions the offline solver does not
  recognise.

## Technology stack and dependencies

| Component | Version tested | Requirement |
|---|---|---|
| Python | 3.13.18 | 3.10 or newer |
| Streamlit | 1.67.0 | `>=1.64,<2` |
| pandas | 3.0.5 | `>=2.0,<4` |
| Browser | Chrome / Edge / Firefox / Safari (current) | JavaScript enabled |

The animations (`player.js`, `tree.js`) use plain JavaScript and SVG, with no
external JS libraries or CDN scripts. Works on Windows, macOS and Linux.

## Installation

1. Install Python 3.10+.
2. Get the code:
   ```bash
   git clone https://github.com/arpit-k16/DFA-NFA-Explorer.git
   cd DFA-NFA-Explorer
   ```
3. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
4. (Optional) For the Gemini fallback, create `.streamlit/secrets.toml` with
   `GEMINI_API_KEY = "your-key"` or set the environment variable
   `GEMINI_API_KEY`. This file is git-ignored; never commit a key.

## How to run

Entry point: `app.py`

```bash
python -m streamlit run app.py
```

Open http://localhost:8501.

## Example

Definition (preset *Ends with "01"*):

| | |
|---|---|
| Type | DFA |
| States | q0, q1, q2 |
| Alphabet | 0, 1 |
| Start / accepting | q0 / q2 |
| δ | q0 –0→ q1, q0 –1→ q0, q1 –0→ q1, q1 –1→ q2, q2 –0→ q1, q2 –1→ q0 |

Input `1101` → path q0 → q0 → q0 → q1 → q2 → **Accepted** ("The whole input was
read. Final states: q2; at least one is accepting.")
Input `0110` → path q0 → q1 → q2 → q0 → q1 → **Rejected**.

Same machine as JSON (Import machine / Export machine):

```json
{"version": 1, "kind": "DFA", "states": ["q0", "q1", "q2"],
 "alphabet": ["0", "1"], "start": "q0", "accepts": ["q2"],
 "transitions": [{"from": "q0", "symbol": "0", "to": ["q1"]},
                 {"from": "q0", "symbol": "1", "to": ["q0"]},
                 {"from": "q1", "symbol": "0", "to": ["q1"]},
                 {"from": "q1", "symbol": "1", "to": ["q2"]},
                 {"from": "q2", "symbol": "0", "to": ["q1"]},
                 {"from": "q2", "symbol": "1", "to": ["q0"]}]}
```

## Project structure

| File | Responsibility |
|---|---|
| `app.py` | **Entry point.** Streamlit layout, sidebar editor, question box, tabs, downloads |
| `automata.py` | Engine: validation, ε-closure, simulation, verdicts, subset construction, analysis, JSON |
| `computation_tree.py` | Builds the tree of all branches and classifies each leaf |
| `regex_to_nfa.py` | Regex parser and Thompson's construction |
| `question_solver.py` | Understands typed questions and builds DFAs/NFAs from them |
| `gemini_generator.py` | Optional AI fallback (needs an API key) |
| `player.js`, `player.css` | Animated state graph, tape and trace |
| `tree.js`, `tree.css` | Animated computation tree |
| `test_*.py` | Automated tests |
| `.streamlit/config.toml` | Theme and server settings |

The engine modules have no Streamlit dependency and can be imported on their own.

## Semantics (how edge cases are handled)

- **Empty string:** a blank input field or a standalone `ε` means the empty
  string. In batch testing, blank lines are ignored; write `ε` to test it.
- **ε-moves:** `ε`, `eps`, `epsilon`, `@` or `<eps>` in the Symbol column. These
  cannot be alphabet symbols. An NFA starts in ε-closure(q₀) and applies the
  closure after every symbol.
- **Partial DFAs:** missing transitions are allowed and shown as a warning. The
  run **dies** at a missing move and rejects; no trap state is added silently.
- **Symbols outside Σ:** shown as a warning; the run rejects at the first such
  symbol.
- **Acceptance:** the whole input must be read and at least one live state must
  be accepting.
- **Invalid definitions** (unknown states, symbols not in Σ, DFA with two targets
  or an ε-move, incomplete rows) are errors and block the run.

## Testing

```bash
python -m unittest test_automata test_app test_gemini_generator test_question_solver test_computation_tree test_regex_to_nfa -v
```

Expected: `Ran 37 tests … OK`. The tests cover all presets, ε-cycles, the empty
string, invalid and partial machines, JSON round trips, NFA→DFA equivalence on
random ε-NFAs, the computation tree against the simulator, Thompson's
construction against Python's `re`, the question solver (58 phrasings, non-regular requests and error cases)
against Python oracles, and the whole UI through Streamlit's AppTest. The Gemini tests mock the
network, so no key is needed.

## Known limitations and troubleshooting

- Alphabet symbols are single characters.
- Limits: 2,000 input symbols, 20,000 characters of batch text, 1 MB JSON,
  400 computation-tree nodes, 64 states for generated machines.
- DFA minimization is not included in this version.
- The offline question solver understands common textbook phrasings; others need
  the Gemini key, and AI-generated machines should be checked with test strings.
- Dense diagrams: drag nodes, zoom, or switch to the circular layout.
- *Port 8501 in use:* `python -m streamlit run app.py --server.port 8502`.
- *ModuleNotFoundError:* re-run `python -m pip install -r requirements.txt` in the
  same Python environment you run Streamlit from.

## Team contributions and acknowledgements

| Member | Contribution |
|---|---|
| [Name – ID] | [Contribution] |
| [Name – ID] | [Contribution] |
| [Name – ID] | [Contribution] |
| [Name – ID] | [Contribution] |

Theory follows Hopcroft, Motwani & Ullman, *Introduction to Automata Theory,
Languages, and Computation* (3rd ed.) and Thompson (1968). Built with Streamlit
(Apache-2.0) and pandas (BSD-3-Clause). No third-party source code is included.
