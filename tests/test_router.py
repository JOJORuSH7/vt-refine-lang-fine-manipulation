import unittest
from router.router import route_instruction


class TestRouter(unittest.TestCase):
    def assertP(self, text, expected, mode=None, places=6):
        result = route_instruction(text)
        self.assertAlmostEqual(result.p_star, expected, places=places, msg=text)
        self.assertTrue(0.0 <= result.p_star <= 1.0, msg=text)
        if mode is not None:
            self.assertEqual(result.mode, mode, msg=text)

    def assertSemantic(self, text, expected, places=6):
        result = route_instruction(text, semantic_backend="offline")
        self.assertAlmostEqual(result.p_star, expected, places=places, msg=text)
        self.assertTrue(0.0 <= result.p_star <= 1.0, msg=text)
        self.assertEqual(result.mode, "semantic_offline", msg=text)

    def test_exact_cases(self):
        cases = [
            ("insert 0%", 0.0),
            ("insert 25%", 0.25),
            ("insert 50%", 0.5),
            ("insert 75%", 0.75),
            ("insert 100%", 1.0),
            ("insert 12.5%", 0.125),
            ("insert 62.5 percent", 0.625),
            ("go 25 percent", 0.25),

            ("insert 1/4", 0.25),
            ("insert 1/2", 0.5),
            ("insert 3/4", 0.75),
            ("insert 1/1", 1.0),

            ("insert 0.0", 0.0),
            ("insert 0.25", 0.25),
            ("insert 0.5", 0.5),
            ("insert 0.75", 0.75),
            ("insert 1.0", 1.0),
            ("insert .75", 0.75),

            ("insert quarter", 0.25),
            ("insert a quarter", 0.25),
            ("insert one quarter", 0.25),
            ("insert one fourth", 0.25),
            ("insert half", 0.5),
            ("insert halfway", 0.5),
            ("insert half way", 0.5),
            ("insert one half", 0.5),
            ("insert three quarters", 0.75),
            ("insert three fourths", 0.75),
            ("go all the way", 1.0),
            ("fully insert", 1.0),
            ("complete insertion", 1.0),
            ("not at all", 0.0),
        ]
        self.assertGreaterEqual(len(cases), 30)
        for text, expected in cases:
            self.assertP(text, expected, mode="exact")

    def test_same_meaning_multiple_forms_should_still_be_exact(self):
        self.assertP("insert 25 percent, a quarter of the way", 0.25, mode="exact")
        self.assertP("insert half, 50%", 0.5, mode="exact")
        self.assertP("insert fully, 100%", 1.0, mode="exact")

    def test_ambiguous_inputs_fallback(self):
        ambiguous = [
            "half or quarter",
            "25% or 50%",
            "1/4 or 3/4",
            "0.25 or 0.75",
        ]
        for text in ambiguous:
            result = route_instruction(text)
            self.assertEqual(result.mode, "fallback_ambiguous", msg=text)
            self.assertAlmostEqual(result.p_star, 0.5, places=6, msg=text)
            self.assertTrue(0.0 <= result.p_star <= 1.0, msg=text)

    def test_unparsed_inputs_fallback(self):
        unparsed = [
            "",
            "   ",
            "asset 00081",
            "step 10",
            "calibrate camera",
            "open gripper",
            "150%",
            "2/1",
        ]
        for text in unparsed:
            result = route_instruction(text)
            self.assertEqual(result.mode, "fallback_unparsed", msg=text)
            self.assertAlmostEqual(result.p_star, 0.5, places=6, msg=text)
            self.assertTrue(0.0 <= result.p_star <= 1.0, msg=text)

    def test_semantic_offline_fallback_cases(self):
        cases = [
            ("insert a bit", 0.25),
            ("insert just a little", 0.25),
            ("make a shallow insertion", 0.25),
            ("barely insert it", 0.25),

            ("go some amount", 0.5),
            ("insert partway", 0.5),
            ("move to the middle depth", 0.5),
            ("do a moderate insertion", 0.5),

            ("insert most of the way", 0.75),
            ("almost fully insert it", 0.75),
            ("not quite all the way", 0.75),
            ("go deep but not complete", 0.75),

            ("do not insert", 0.0),
            ("no insertion", 0.0),
            ("keep it outside", 0.0),

            ("finish insertion", 1.0),
            ("bottom it out", 1.0),
            ("push until seated", 1.0),
        ]
        for text, expected in cases:
            self.assertSemantic(text, expected)

    def test_numeric_first_over_semantic_fallback(self):
        self.assertP("insert 25% even though that is most of the way", 0.25, mode="exact")
        self.assertP("go 0.75 but call it a little", 0.75, mode="exact")
        self.assertP("insert 1/2, not quite all the way", 0.5, mode="exact")

    def test_semantic_does_not_resolve_exact_ambiguity(self):
        result = route_instruction(
            "insert 25% or 50%, whichever is partway",
            semantic_backend="offline",
        )
        self.assertEqual(result.mode, "fallback_ambiguous")
        self.assertAlmostEqual(result.p_star, 0.5, places=6)

    def test_semantic_offline_irrelevant_controls_still_fallback(self):
        for text in ["asset 00081", "step 10", "calibrate camera", "open gripper", "run the eval"]:
            result = route_instruction(text, semantic_backend="offline")
            self.assertEqual(result.mode, "fallback_unparsed", msg=text)
            self.assertAlmostEqual(result.p_star, 0.5, places=6, msg=text)

    def test_softened_full_phrases_are_not_exact_full(self):
        for text in ["almost fully insert it", "not quite all the way", "nearly full insertion"]:
            result = route_instruction(text, semantic_backend="offline")
            self.assertEqual(result.mode, "semantic_offline", msg=text)
            self.assertAlmostEqual(result.p_star, 0.75, places=6, msg=text)


if __name__ == "__main__":
    unittest.main()
