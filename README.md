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

## Phones and tablets

The simulator adapts to portrait and landscape, including narrow 320px screens.
The layered graph runs vertically in narrow panels and horizontally in wider
ones. Rotating the phone refits the graph without resetting the current step.
Manually dragged state positions are preserved. Controls have 44px touch targets;
long tapes and trace tables scroll within their own panels.

Swipe over the graph to scroll the page. Tap **Move graph** to enable dragging
states and panning, then **Done moving** to restore page scrolling. Use the +/−
buttons to zoom and **Fit** to bring the whole graph back into view.

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
  and minimization. No Streamlit dependency.
- `app.py`: Streamlit editor, tabs, downloads, and component data.
- `player.js` / `player.css`: an inline Streamlit v2 component with local
  animation and SVG interaction. No CDN scripts or frontend build step.
- `test_automata.py` / `test_app.py`: engine and Streamlit regression tests.

## Verify

```powershell
python -m unittest test_automata test_app -v
```

Tests cover all preset languages over short strings, ε-cycles, empty strings,
missing/invalid transitions, JSON round trips, diagnostics, bounded conversion,
randomized NFA equivalence after determinization/minimization, and UI workflows.
The custom player's rendered interactions are also checked in the browser.
