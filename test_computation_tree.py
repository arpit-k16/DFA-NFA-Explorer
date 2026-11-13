"""Tests for the computation tree (python -m unittest test_computation_tree -v)."""
from itertools import product
import random
import unittest

import pandas as pd

from automata import EPS, PRESETS, build_machine, machine_from_spec, simulate
from computation_tree import accepting_path, build_tree


class TreeTests(unittest.TestCase):
    def test_verdict_matches_simulator(self):
        random.seed(7)
        machines = [machine_from_spec(spec)[0] for spec in PRESETS.values()]
        for _ in range(15):
            rows = [(u, a, v) for u in "abc" for a in ["0", "1", EPS] for v in "abc"
                    if random.random() < .25]
            m, errors, _ = build_machine("NFA", "a,b,c", "0,1", "a", random.choice(["c", "b,c", ""]),
                                         pd.DataFrame(rows, columns=["From", "Symbol", "To"]))
            self.assertFalse(errors)
            machines.append(m)
        for m in machines:
            for n in range(5):
                for chars in product(m["alphabet"], repeat=n):
                    word = "".join(chars)
                    tree = build_tree(m, word, max_nodes=5000)
                    self.assertFalse(tree["truncated"])
                    self.assertEqual(tree["accepted"], simulate(m, word)[1], word)

    def test_branches_and_path(self):
        m = machine_from_spec(PRESETS['Contains "ab"'])[0]
        tree = build_tree(m, "baab")
        self.assertEqual(tree["summary"]["accepting"], 1)
        self.assertEqual(tree["summary"]["dead"], 1)
        path = accepting_path(tree)
        self.assertEqual([n["state"] for n in path], ["s0", "s0", "s0", "s1", "s2"])

    def test_dfa_is_single_path_and_limit(self):
        m = machine_from_spec(PRESETS['Ends with "01"'])[0]
        self.assertEqual(build_tree(m, "1101")["summary"]["branches"], 1)
        nfa = machine_from_spec(PRESETS['Contains "ab"'])[0]
        self.assertTrue(build_tree(nfa, "ab" * 40, max_nodes=50)["truncated"])


if __name__ == "__main__":
    unittest.main()
