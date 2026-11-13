import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

from automata import PRESETS, DEFAULT_PRESET, machine_from_spec, export_machine
from gemini_generator import generate, parse_proposal


class GeneratorTests(unittest.TestCase):
    def proposal(self):
        machine, _, _ = machine_from_spec(PRESETS[DEFAULT_PRESET])
        return json.dumps({"interpretation": "Binary strings ending in 01",
                           "error": "", "machine": json.loads(export_machine(machine))})

    def test_valid_and_invalid_machine(self):
        self.assertEqual(parse_proposal(self.proposal())["start"], "q0")
        data = json.loads(self.proposal())
        data["machine"]["start"] = "missing"
        with self.assertRaises(ValueError):
            parse_proposal(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "nonregular"):
            parse_proposal(json.dumps({"interpretation": "", "error": "nonregular"}))

    @patch("gemini_generator.urlopen")
    def test_request_and_response(self, send):
        response = MagicMock()
        response.read.return_value = json.dumps({"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": self.proposal()}]}}]}).encode()
        send.return_value.__enter__.return_value = response
        self.assertEqual(generate("ends in 01", "test-secret")["start"], "q0")
        request = send.call_args.args[0]
        self.assertNotIn("test-secret", request.full_url)
        self.assertNotIn("test-secret", request.data.decode())
        send.side_effect = HTTPError(request.full_url, 403, "private details", {}, None)
        with self.assertRaisesRegex(ValueError, "HTTP 403"):
            generate("ends in 01", "test-secret")

    @patch("gemini_generator.time.sleep")
    @patch("gemini_generator.urlopen")
    def test_overload_retries_are_bounded(self, send, sleep):
        send.side_effect = [HTTPError("https://example.com", 503, "busy", {}, None)
                            for _ in range(3)]
        with self.assertRaisesRegex(ValueError, "overloaded"):
            generate("ends in 01", "test-secret")
        self.assertEqual(send.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    @patch("gemini_generator.time.sleep")
    @patch("gemini_generator.urlopen")
    def test_overload_then_success(self, send, sleep):
        response = MagicMock()
        response.read.return_value = json.dumps({"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": self.proposal()}]}}]}).encode()
        context = MagicMock()
        context.__enter__.return_value = response
        send.side_effect = [HTTPError("https://example.com", 503, "busy", {}, None), context]
        self.assertEqual(generate("ends in 01", "test-secret")["start"], "q0")
        self.assertEqual(send.call_count, 2)


if __name__ == "__main__":
    unittest.main()
