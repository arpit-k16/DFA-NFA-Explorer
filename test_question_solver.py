"""Tests for the plain-English question solver (python -m unittest test_question_solver -v)."""
from itertools import product
import unittest

from automata import PRESETS, machine_from_spec, simulate
from question_solver import EXAMPLE_QUESTIONS, NotUnderstood, solve


def words(alphabet, max_len=6):
    for n in range(max_len + 1):
        for chars in product(alphabet, repeat=n):
            yield "".join(chars)


class LanguageTests(unittest.TestCase):
    """Each generated machine must agree with a Python oracle on all short strings."""

    CASES = [
        ("DFA over {0,1} for strings ending with 01", "01", lambda w: w.endswith("01")),
        ("strings over {a,b} starting with ab", "ab", lambda w: w.startswith("ab")),
        ("strings over {a,b} containing the substring aba", "ab", lambda w: "aba" in w),
        ("strings over {a,b} that do not contain aa", "ab", lambda w: "aa" not in w),
        ("strings over {a,b} not ending with ab", "ab", lambda w: not w.endswith("ab")),
        ("strings without bb over {a,b}", "ab", lambda w: "bb" not in w),
        ("even number of a's and odd number of b's", "ab",
         lambda w: w.count("a") % 2 == 0 and w.count("b") % 2 == 1),
        ("number of a's divisible by 3 over {a,b}", "ab", lambda w: w.count("a") % 3 == 0),
        ("strings over {0,1} with exactly two 1s", "01", lambda w: w.count("1") == 2),
        ("strings over {0,1} with at least 3 0s", "01", lambda w: w.count("0") >= 3),
        ("strings over {a,b} of length at most 2", "ab", lambda w: len(w) <= 2),
        ("strings over {a,b} of odd length", "ab", lambda w: len(w) % 2 == 1),
        ("binary numbers divisible by 5", "01", lambda w: int(w or "0", 2) % 5 == 0),
        ("binary strings starting with 1 or ending with 00", "01",
         lambda w: w.startswith("1") or w.endswith("00")),
        ("strings over {a,b} that start with a and contain bb", "ab",
         lambda w: w.startswith("a") and "bb" in w),
        ("NFA for strings over {a,b} containing aba", "ab", lambda w: "aba" in w),
        ("NFA over {0,1} for strings ending with 11", "01", lambda w: w.endswith("11")),
        ("Construct a DFA that accepts strings that do not contain consecutive 11", "01",
         lambda w: "11" not in w),
        ("no two consecutive 1s", "01", lambda w: "11" not in w),
        ("binary strings without consecutive 0s", "01", lambda w: "00" not in w),
        ("strings over {a,b} with no three consecutive a's", "ab", lambda w: "aaa" not in w),
        ("strings over {a,b} containing two consecutive b's", "ab", lambda w: "bb" in w),
    ]

    def test_languages_match_oracle(self):
        for question, alphabet, oracle in self.CASES:
            with self.subTest(question):
                result = solve(question)
                machine, errors, _ = machine_from_spec(result["spec"])
                self.assertFalse(errors)
                for w in words(alphabet):
                    self.assertEqual(simulate(machine, w)[1], oracle(w), w)

    def test_dfa_shapes(self):
        self.assertEqual(len(solve("strings over {0,1} ending with 01")["machine"]["states"]), 3)
        self.assertEqual(len(solve("binary numbers divisible by 5")["machine"]["states"]), 5)
        self.assertIn("dead", solve("strings over {a,b} starting with ab")["machine"]["states"])

    def test_nfa_requested(self):
        self.assertEqual(solve("NFA for strings over {a,b} ending with ab")["machine"]["kind"], "NFA")


class QuestionTests(unittest.TestCase):
    def setUp(self):
        self.current = machine_from_spec(PRESETS['Contains "ab"'])[0]

    def test_test_strings_in_question(self):
        result = solve("Construct a DFA over {0,1} for strings ending with 01 and check 1101, 0110")
        self.assertEqual([(t["String"], t["Result"].endswith("Accepted")) for t in result["tests"]],
                         [("1101", True), ("0110", False)])

    def test_membership_on_current_machine(self):
        result = solve("Does the machine accept baab and bbb?", self.current)
        self.assertIsNone(result["spec"])
        self.assertEqual([t["Result"].endswith("Accepted") for t in result["tests"]], [True, False])
        self.assertTrue(solve("Is 1101 accepted?", self.current)["tests"])

    def test_convert(self):
        dfa = solve("Convert this NFA to a DFA", self.current)
        self.assertEqual(dfa["machine"]["kind"], "DFA")

    def test_examples_all_work(self):
        for question in EXAMPLE_QUESTIONS:
            with self.subTest(question):
                self.assertTrue(solve(question, self.current)["title"])

    def test_unknown_question(self):
        with self.assertRaises(NotUnderstood):
            solve("language of palindromes", self.current)
        with self.assertRaises(NotUnderstood):
            solve("   ")
        # English words after "contain" must never become the pattern.
        self.assertEqual(solve("strings that do not contain consecutive 11")["machine"]["alphabet"],
                         ["0", "1"])


if __name__ == "__main__":
    unittest.main()
