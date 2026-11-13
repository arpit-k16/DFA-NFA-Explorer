"""Streamlit UI regression tests (python -m unittest test_app -v)."""
import unittest

from streamlit.testing.v1 import AppTest

from automata import PRESETS


class AppTests(unittest.TestCase):
    def test_presets_empty_string_validation_and_reload(self):
        app = AppTest.from_file("app.py", default_timeout=15).run()
        self.assertFalse(app.exception)
        for name in PRESETS:
            app.selectbox(key="preset").select(name).run()
            self.assertFalse(app.exception, name)
            self.assertFalse(app.error, name)
            version = app.session_state["version"]
            app.text_input(key=f"input_{version}").set_value("ε").run()
            self.assertFalse(app.exception)
        version = app.session_state["version"]
        app.text_input(key=f"start_{version}").set_value("missing").run()
        self.assertTrue(app.error)
        self.assertFalse(app.exception)
        next(b for b in app.button if b.label == "Reload example").click().run()
        self.assertFalse(app.error)
        self.assertFalse(app.exception)

    def test_ask_question_builds_and_loads_machine(self):
        app = AppTest.from_file("app.py", default_timeout=15).run()
        app.text_area(key="question").set_value(
            "DFA over {a,b} for strings with an even number of a's. Check aba, ab").run()
        next(b for b in app.button if b.label == "Solve").click().run()
        self.assertFalse(app.exception)
        result = app.session_state["qa_result"]
        self.assertEqual([t["String"] for t in result["tests"]], ["aba", "ab"])
        version = app.session_state["version"]
        self.assertEqual(app.text_input(key=f"alpha_{version}").value, "a, b")
        self.assertFalse(app.error)

    def test_question_about_current_machine(self):
        app = AppTest.from_file("app.py", default_timeout=15).run()
        app.text_area(key="question").set_value("Is 1101 accepted?").run()
        next(b for b in app.button if b.label == "Solve").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state["qa_result"]["tests"][0]["Result"].endswith("Accepted"))


if __name__ == "__main__":
    unittest.main()
