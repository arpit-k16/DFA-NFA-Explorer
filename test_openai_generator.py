"""Tests for the OpenAI adapter with the network mocked (no key needed)."""
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from automata import DEFAULT_PRESET, PRESETS, export_machine, machine_from_spec
from openai_generator import generate


class OpenAITests(unittest.TestCase):
    def reply(self):
        machine, _, _ = machine_from_spec(PRESETS[DEFAULT_PRESET])
        content = json.dumps({"interpretation": "Binary strings ending in 01", "error": "",
                              "machine": json.loads(export_machine(machine))})
        return json.dumps({"choices": [{"finish_reason": "stop",
                                        "message": {"content": content}}]}).encode()

    @patch("openai_generator.urlopen")
    def test_request_and_response(self, send):
        response = MagicMock()
        response.read.return_value = self.reply()
        send.return_value.__enter__.return_value = response
        self.assertEqual(generate("ends in 01", "sk-secret", "test-model")["start"], "q0")
        request = send.call_args.args[0]
        self.assertNotIn("sk-secret", request.full_url)
        self.assertNotIn("sk-secret", request.data.decode())
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-secret")
        self.assertEqual(json.loads(request.data)["model"], "test-model")

    @patch("openai_generator.time.sleep")
    @patch("openai_generator.urlopen")
    def test_errors_are_explained(self, send, _sleep):
        for code, text in [(401, "rejected the API key"), (404, "unavailable"), (429, "quota")]:
            send.side_effect = HTTPError("u", code, "details", {}, None)
            with self.subTest(code), self.assertRaisesRegex(ValueError, text):
                generate("ends in 01", "sk-secret")
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            generate("ends in 01", "")


if __name__ == "__main__":
    unittest.main()
