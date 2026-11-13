"""Run with python -m unittest -v. No test-only dependencies required."""
import itertools
import json
import random
import unittest

import pandas as pd

from automata import (
    EPS, PRESETS, analyze_machine, build_machine, determinize, eps_closure,
    export_machine, import_machine, machine_from_spec, simulate,
)


def machine(kind="NFA", transitions=(), accepts="c", states="a,b,c", alphabet="0,1", start="a"):
    result, errors, _ = build_machine(kind, states, alphabet, start, accepts,
                                     pd.DataFrame(transitions, columns=["From", "Symbol", "To"]))
    if errors:
        raise AssertionError(errors)
    return result


def words(alphabet, length=5):
    for size in range(length + 1):
        for chars in itertools.product(alphabet, repeat=size):
            yield "".join(chars)


class AutomataTests(unittest.TestCase):
    def test_preset_languages(self):
        predicates = [lambda w:w.endswith("01"), lambda w:w.count("a") % 2 == 0,
                      lambda w:int(w or "0", 2) % 3 == 0, lambda w:w.startswith("10"),
                      lambda w:"ab" in w, lambda w:w.endswith("b") and set(w[:-1]) <= {"a"}]
        for spec, predicate in zip(PRESETS.values(), predicates):
            m, errors, _ = machine_from_spec(spec)
            self.assertFalse(errors)
            for word in words(m["alphabet"]):
                self.assertEqual(simulate(m, word)[1], predicate(word), (spec["blurb"], word))

    def test_empty_input_and_epsilon_cycles(self):
        m = machine(transitions=[("a", EPS, "b"), ("b", EPS, "a,c")])
        self.assertEqual(eps_closure(["a"], m["trans"])[0], frozenset("abc"))
        self.assertTrue(simulate(m, "")[1])
        self.assertEqual(simulate(m, ""), simulate(m, EPS))
        self.assertFalse(simulate(m, "0")[1])

    def test_closure_after_symbol_and_merged_branches(self):
        m = machine(transitions=[("a", "0", "a,b"), ("b", EPS, "c")])
        steps, ok, final, stuck = simulate(m, "00")
        self.assertTrue(ok)
        self.assertEqual(final, frozenset("abc"))
        self.assertIn(("a", "0", "b"), steps[-1]["taken"])
        self.assertIn(("b", EPS, "c"), steps[-1]["eps"])
        self.assertIsNone(stuck)

    def test_partial_dfa_and_unknown_input(self):
        m = machine("DFA", [("a", "0", "c")])
        for word in ("1", "x", "01"):
            trace, ok, final, stuck = simulate(m, word)
            self.assertFalse(ok)
            self.assertEqual(final, frozenset())
            self.assertEqual(stuck, 1 if word == "01" else 0)
        self.assertTrue(simulate(m, "0")[1])

    def test_validation_rejects_malformed_definitions(self):
        cases = [("DFA", [("a", EPS, "b")]), ("DFA", [("a", "0", "a,b")]),
                 ("NFA", [("z", "0", "a")]), ("NFA", [("a", "x", "c")]),
                 ("NFA", [("a", "0", ", ;")]), ("NFA", [("a", "0", None)]),
                 ("OTHER", [])]
        for kind, rows in cases:
            _, errors, _ = build_machine(kind, "a,b,c", "0,1", "a", "c",
                                         pd.DataFrame(rows, columns=["From", "Symbol", "To"]))
            self.assertTrue(errors, (kind, rows))

    def test_conversion_preserves_languages(self):
        random.seed(47)
        machines = [machine_from_spec(spec)[0] for spec in PRESETS.values()]
        for _ in range(12):
            edges = [(u, a, v) for u in "abc" for a in ["0", "1", EPS] for v in "abc"
                     if random.random() < .22]
            machines.append(machine(transitions=edges, accepts=random.choice(["", "a", "b,c"])))
        for m in machines:
            dfa, _ = determinize(m)
            for word in words(m["alphabet"]):
                expected = simulate(m, word)[1]
                self.assertEqual(simulate(dfa, word)[1], expected)

    def test_conversion_guard(self):
        m = machine(transitions=[("a", "0", "b")])
        with self.assertRaises(ValueError):
            determinize(m, max_states=1)

    def test_import_export_roundtrip_and_invalid_json(self):
        for spec in PRESETS.values():
            m = machine_from_spec(spec)[0]
            restored = machine_from_spec(import_machine(export_machine(m)))[0]
            self.assertEqual(json.loads(export_machine(m)), json.loads(export_machine(restored)))
        for raw in ('[]', '{}', '{"version":2}', 'not json'):
            with self.assertRaises(ValueError):
                import_machine(raw)

    def test_diagnostics(self):
        m = machine(transitions=[("a", EPS, "b"), ("b", "0", "c"), ("c", "1", "c")],
                    states="a,b,c,isolated")
        info = analyze_machine(m)
        self.assertEqual(info["shortest"], "0")
        self.assertEqual(info["unreachable"], {"isolated"})
        self.assertEqual(info["dead"], {"isolated"})
        self.assertFalse(info["complete"])
        self.assertIsNone(analyze_machine(machine(accepts=""))["shortest"])


if __name__ == "__main__":
    unittest.main()
