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



if __name__ == "__main__":
    unittest.main()
