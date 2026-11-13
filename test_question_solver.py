"""Tests for the plain-English question solver (python -m unittest test_question_solver -v)."""
from itertools import product
import unittest

from automata import PRESETS, machine_from_spec, simulate
from question_solver import EXAMPLE_QUESTIONS, FinalAnswer, NotRegular, NotUnderstood, solve


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
        ("Construct a DFA that accepts strings that start and end with the same symbol.", "ab",
         lambda w: len(w) > 0 and w[0] == w[-1]),
        ("strings over {0,1} that begin and end with the same symbol", "01",
         lambda w: len(w) > 0 and w[0] == w[-1]),
        ("strings that start and end with different symbols", "ab",
         lambda w: len(w) > 0 and w[0] != w[-1]),
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
                try:
                    self.assertTrue(solve(question, self.current)["title"])
                except FinalAnswer as answer:  # e.g. the palindrome example is explained, not built
                    self.assertIn("non-regular", str(answer))

    def test_unknown_question(self):
        with self.assertRaises(NotUnderstood):
            solve("language of palindromes", self.current)
        with self.assertRaises(NotUnderstood):
            solve("   ")
        # English words after "contain" must never become the pattern.
        self.assertEqual(solve("strings that do not contain consecutive 11")["machine"]["alphabet"],
                         ["0", "1"])
        result = solve("strings that start and end with the same symbol. Check a, aba, ab, ε")
        self.assertEqual([(t["String"], t["Result"].endswith("Accepted")) for t in result["tests"]],
                         [("a", True), ("aba", True), ("ab", False), ("ε", False)])


def count_overlapping(w, p):
    return sum(1 for i in range(len(w) - len(p) + 1) if w[i:i + len(p)] == p)


def followed(w, x, y):
    return all(w[i + 1:i + 1 + len(y)] == y for i, c in enumerate(w) if c == x)


def preceded(w, x, y):
    return all(i >= len(y) and w[i - len(y):i] == y for i, c in enumerate(w) if c == x)


class EdgeCaseTests(unittest.TestCase):
    """Wider question coverage, each checked against a Python oracle (strings up to length 7)."""

    B = staticmethod(lambda w: int(w or "0", 2))
    CASES = [
        ("third symbol from the end is 1", "01", lambda w: len(w) >= 3 and w[-3] == "1"),
        ("NFA for strings whose 3rd symbol from the right is 1", "01", lambda w: len(w) >= 3 and w[-3] == "1"),
        ("second symbol is b", "ab", lambda w: len(w) >= 2 and w[1] == "b"),
        ("first symbol is not a", "ab", lambda w: not w.startswith("a")),
        ("penultimate symbol is a", "ab", lambda w: len(w) >= 2 and w[-2] == "a"),
        ("every a is followed by b", "ab", lambda w: followed(w, "a", "b")),
        ("every 0 is immediately followed by 11", "01", lambda w: followed(w, "0", "11")),
        ("every b is preceded by a", "ab", lambda w: preceded(w, "b", "a")),
        ("strings consisting of only a's", "ab", lambda w: set(w) <= {"a"}),
        ("exactly two occurrences of ab", "ab", lambda w: count_overlapping(w, "ab") == 2),
        ("strings that contain aa exactly once", "ab", lambda w: count_overlapping(w, "aa") == 1),
        ("odd binary numbers", "01", lambda w: int(w or "0", 2) % 2 == 1),
        ("binary numbers which leave remainder 2 when divided by 5", "01", lambda w: int(w or "0", 2) % 5 == 2),
        ("n_a(w) mod 3 = 1", "ab", lambda w: w.count("a") % 3 == 1),
        ("number of a's and b's are both even", "ab", lambda w: w.count("a") % 2 == 0 and w.count("b") % 2 == 0),
        ("|w| >= 2", "ab", lambda w: len(w) >= 2),
        ("length ≠ 2", "ab", lambda w: len(w) != 2),
        ("more than one a", "ab", lambda w: w.count("a") > 1),
        ("strings with no a's", "ab", lambda w: "a" not in w),
        ("strings that neither start with a nor end with b", "ab",
         lambda w: not w.startswith("a") and not w.endswith("b")),
        ("strings that contain both ab and ba", "ab", lambda w: "ab" in w and "ba" in w),
        ("strings that end with either 00 or 11", "01", lambda w: w.endswith("00") or w.endswith("11")),
        ("strings that start with a and end with b or contain aa", "ab",
         lambda w: (w.startswith("a") and w.endswith("b")) or "aa" in w),
        ("DFA for (a+b)*abb", "ab", lambda w: w.endswith("abb")),
        ("DFA for the regular expression (a + b)* abb", "ab", lambda w: w.endswith("abb")),
        ("ε-NFA for (01)*", "01", lambda w: w == "01" * (len(w) // 2)),
        ("accepts all strings over {a,b}", "ab", lambda w: True),
        ("accepts only the empty string", "ab", lambda w: w == ""),
        ("strings over a and b that end with ab", "ab", lambda w: w.endswith("ab")),
        ("strings that start with a and start with b", "ab", lambda w: False),
        ("Construct an NFA that accepts strings containing 00 or 11 as substrings.", "01",
         lambda w: "00" in w or "11" in w),
        ("NFA for strings that start with 01 or end with 10", "01",
         lambda w: w.startswith("01") or w.endswith("10")),
        ("NFA for strings containing 01, 10 or 11", "01", lambda w: "01" in w or "10" in w or "11" in w),
    ]

    def test_cases_match_oracle(self):
        for question, alphabet, oracle in self.CASES:
            with self.subTest(question):
                machine = solve(question)["machine"]
                self.assertEqual("".join(machine["alphabet"]), alphabet)
                for n in range(8):
                    for chars in product(alphabet, repeat=n):
                        w = "".join(chars)
                        self.assertEqual(simulate(machine, w)[1], oracle(w), w)

    def test_union_nfa_is_the_textbook_one(self):
        machine = solve("Construct an NFA that accepts strings containing 00 or 11 as substrings.")["machine"]
        self.assertEqual((machine["kind"], len(machine["states"])), ("NFA", 4))

    def test_non_regular_languages_are_explained(self):
        for question in ["DFA for palindromes over {a,b}", "a^n b^n", "0^n1^n where n>=1",
                         "strings with equal number of a's and b's", "more a's than b's",
                         "L = {ww | w in {a,b}*}", "strings of prime length", "balanced parentheses"]:
            with self.subTest(question), self.assertRaisesRegex(NotRegular, "non-regular"):
                solve(question)

    def test_definite_answers_without_machine(self):
        for question, message in [("minimize this DFA", "minimization"),
                                  ("binary numbers divisible by 0", "at least 1"),
                                  ("binary numbers divisible by 100", "64 states"),
                                  ("11th symbol from the end is 0", "NFA")]:
            with self.subTest(question), self.assertRaisesRegex(FinalAnswer, message):
                solve(question)

    def test_empty_and_universal_notes_and_tricky_inputs(self):
        self.assertIn("empty (∅)", " ".join(solve("strings that start with a and start with b")["steps"]))
        self.assertIn("Σ", " ".join(solve("accepts all strings over {a,b}")["steps"]))
        result = solve("strings over {0,1} ending with 01 and check 1101, 1021, empty string")
        self.assertEqual([(t["String"], t["Result"].endswith("Accepted")) for t in result["tests"]],
                         [("1101", True), ("1021", False), ("ε", False)])
        current = machine_from_spec(PRESETS['Ends with "01"'])[0]
        self.assertEqual(solve("is the empty string accepted?", current)["tests"][0]["String"], "ε")
        self.assertFalse(solve("Does the machine accept 101?", current)["spec"])

if __name__ == "__main__":
    unittest.main()
