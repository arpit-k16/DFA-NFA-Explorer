"""Tests for Thompson's construction (python -m unittest test_regex_to_nfa -v)."""
from itertools import product
import re
import unittest

from automata import machine_from_spec, simulate
from regex_to_nfa import RegexError, regex_spec, regex_to_nfa


def python_regex(expr):
    return re.compile(expr.replace(" ", "").replace("+", "|").replace("ε", "(?:)")
                      .replace("()", "(?:)"))


class ThompsonTests(unittest.TestCase):
    EXPRESSIONS = ["(a|b)*ab", "(a+b)*abb", "a*b*", "(ab)*", "a(b|ε)c", "0(0|1)*1",
                   "(0|1)*00(0|1)*", "a?b", "((a|b)(a|b))*", "a|b|c", "(a*b*)*", "ε|a"]

    def test_matches_python_re(self):
        for expr in self.EXPRESSIONS:
            with self.subTest(expr):
                m = regex_to_nfa(expr)
                oracle = python_regex(expr)
                for n in range(7):
                    for chars in product(m["alphabet"], repeat=n):
                        w = "".join(chars)
                        self.assertEqual(simulate(m, w)[1], bool(oracle.fullmatch(w)), w)

    def test_thompson_shape(self):
        m = regex_to_nfa("(a|b)*ab")
        self.assertEqual(m["start"], "q0")
        self.assertEqual(len(m["accepts"]), 1)
        self.assertFalse([k for k in m["trans"] if k[0] == m["accepts"][0]],
                         "accepting state has no outgoing moves")

    def test_spec_loads_in_editor(self):
        spec = regex_spec("(a|b)*ab")
        machine, errors, _ = machine_from_spec(spec)
        self.assertFalse(errors)
        self.assertTrue(simulate(machine, spec["sample"])[1])

    def test_errors(self):
        for bad in ["", "(ab", "ab)", "*a", "a-b", "ε", "a" * 300]:
            with self.subTest(bad), self.assertRaises(RegexError):
                regex_to_nfa(bad)


if __name__ == "__main__":
    unittest.main()
