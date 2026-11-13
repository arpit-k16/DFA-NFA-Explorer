# DFA/NFA Explorer

An interactive Streamlit workbench for deterministic finite automata (DFA) and
nondeterministic finite automata with empty moves (ε-NFA).

## Run

Requires Python 3.10+.

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open [localhost:8501](http://localhost:8501).

## Ask a question

Type a question at the top of the page and click **Solve**. The built-in solver
(`question_solver.py`) works offline, with no API key, for the common textbook
patterns:

- *ends with / starts with / contains / does not contain* a substring
- *even/odd number of a's*, *number of a's divisible by k*, *exactly / at least /
  at most n 1s*
- *even/odd length*, *length at least / at most / exactly n*
- *binary numbers divisible by n*
- combinations with *and*, *or*, *not*
- *… and check 1101, 0110* tests those strings on the new machine
- questions about the loaded machine: *Is 1101 accepted?*, *Convert this NFA to a
  DFA*, *Shortest accepted string*

The answer shows the language, the DFA (or a classic NFA when one is
asked for), the transition table, accepted/rejected verdicts with the state path,
and example strings. The machine is loaded into the simulator automatically.
Questions the rules don't recognize go to Gemini when `GEMINI_API_KEY` is set.

## Generate with Gemini

Create a Google Gemini API key and store it locally in `.streamlit/secrets.toml`
(this file is excluded from Git):

```toml
GEMINI_API_KEY = "your-replacement-key"
```

Alternatively set the server environment variable `GEMINI_API_KEY`. Restart
Streamlit after configuring it. `GEMINI_MODEL` optionally overrides the default
`gemini-3.5-flash-lite` model; availability depends on your Google account.
No additional Python dependency is needed.

Enter a language description, click **Generate automaton**, review the
interpretation and transition preview, then click **Use generated machine**.
The existing simulator and Machine insights transition matrix use that machine.
Descriptions are sent to Google. Credentials stay on the server and are sent
only as the API authentication header. Never commit a key or paste it into chat.
Revoke any key that has been exposed.

Generated machines pass structural validation, which does not prove that they
recognize the intended language. Test accepted and rejected examples. The model
is instructed to flag ambiguity and nonregular languages, but can still make
mistakes. Each request attempt has a 60-second timeout and bounded response/machine
sizes. Temporary overload errors are retried twice with short delays.

## Explore

- Choose one of six examples or edit the machine in the sidebar. Add and remove
  transition rows directly in the table. Multiple NFA targets use commas.
- Enter a string, then play, pause, step, scrub, or jump to the result. Adjust
  playback speed from 0.5× to 4×. Input or machine edits reset the run.
- The tape, state set, exact transition highlights, and clickable trace stay in
  sync. Consuming moves are indigo; empty moves are amber and dashed. Accepting
  states have double rings and turn green when the completed run accepts.
- Drag states, pan the canvas, scroll to zoom, fit the graph, or switch between
  layered and circular layouts. Select a state to inspect its transitions.
- With the canvas focused: Space plays/pauses, arrows step, Home restarts, and
  End jumps to the result.
- Test multiple strings, inspect a transition matrix, find dead/unreachable
  states, and discover a shortest accepted string.
- Export/import machine JSON. Download the graph as standalone SVG, the trace
  as CSV, and batch results as CSV.

## Semantics and limits

Alphabet symbols are single characters. States use comma/whitespace-separated
names. `ε`, `eps`, `epsilon`, `@`, and `<eps>` in transition symbols denote empty
moves; these cannot be alphabet symbols. In input strings, **only a standalone
`ε` or an empty field** denotes empty input. Other characters, including spaces,
are literal. Blank lines in batch input are ignored; use `ε` to test emptiness.

An NFA starts in the ε-closure of its start state and computes
`ε-closure(move(current, symbol))` after each symbol. State sets represent
possible states, not counts of distinct execution paths. A run accepts only
when the entire input is consumed and at least one live state is accepting.
Partial DFAs are supported: missing moves reject. Empty accepting sets are valid.

Single inputs are limited to 2,000 characters; batch text to 20,000 characters;
JSON uploads to 1 MB. Large or dense diagrams
may need dragging, zooming, or a different layout to separate their labels.

## Project structure

- `automata.py`: parsing, validation, simulation, analysis, JSON, conversion,
  and NFA→DFA conversion. No Streamlit dependency.
- `app.py`: Streamlit editor, tabs, downloads, and component data.
- `player.js` / `player.css`: an inline Streamlit v2 component with local
  animation and SVG interaction. No CDN scripts or frontend build step.
- `test_automata.py` / `test_app.py`: engine and Streamlit regression tests.

## Verify

```powershell
python -m unittest test_automata test_app test_gemini_generator test_question_solver -v
```

Tests cover all preset languages over short strings, ε-cycles, empty strings,
missing/invalid transitions, JSON round trips, diagnostics, bounded conversion,
randomized NFA equivalence after determinization, and UI workflows.
The custom player's rendered interactions are also checked in the browser.
