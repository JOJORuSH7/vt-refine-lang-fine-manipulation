"""18-case OOV / typo regression test for the 4-tier router.

Run:
    cd ~/work/vt-refine
    ROUTER_SEMANTIC_BACKEND=auto python3 -m unittest tests.test_router_typos -v

Backend can also be 'offline' or 'embedding' to verify regex anchors plus
fuzzy correction handle most cases without the SBERT model.
"""

import os
import sys
import unittest

# Allow running from repo root regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from router.router import route_instruction


class TestRouterOOVTypos(unittest.TestCase):
    """18-case test: 16 numeric p_star + 2 fallback_unparsed."""

    NUMERIC_CASES = [
        # (input, expected_p_star)
        ("insert 25%",                    0.25),
        ("insert half",                   0.5),
        ("go to 0.75",                    0.75),
        ("insert a little",               0.25),
        ("barely insert",                 0.25),
        ("insert most of the way",        0.75),
        ("insert a litlle bitt",          0.25),  # double typo
        ("insrt halfway",                 0.5),   # typo
        ("barly insert",                  0.25),  # typo
        ("shove it in just a hair",       0.25),
        ("drive it home",                 1.0),
        ("nudge it in slightly",          0.25),
        ("push deep but stop short",      0.75),
        ("engage just enough to feel it", 0.25),
        ("insert until snug",             0.75),
        ("nearly bottom out",             0.75),
    ]

    FALLBACK_CASES = [
        "asset 00081",
        "what time is it",
    ]

    def test_numeric_p_star(self):
        """16 cases must match expected p_star within tol=0.001."""
        for text, expected in self.NUMERIC_CASES:
            with self.subTest(text=text):
                result = route_instruction(text)
                self.assertAlmostEqual(
                    result.p_star, expected, delta=0.001,
                    msg=f"input={text!r}: expected p_star={expected}, "
                        f"got p_star={result.p_star} (mode={result.mode})",
                )
                self.assertTrue(0.0 <= result.p_star <= 1.0,
                    msg=f"p_star out of range: {result.p_star}")

    def test_fallback_unparsed_mode(self):
        """OOV inputs must take mode 'fallback_unparsed'."""
        for text in self.FALLBACK_CASES:
            with self.subTest(text=text):
                result = route_instruction(text)
                self.assertEqual(
                    result.mode, "fallback_unparsed",
                    msg=f"input={text!r}: expected mode='fallback_unparsed', "
                        f"got mode={result.mode!r} (p_star={result.p_star})",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
