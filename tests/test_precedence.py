"""Precedence: every rule that votes, tested under plain CPython.

The model is replaced by scripted answers, so nothing here measures what a
model does. What is asserted is the part a validator recomputes and compares:
the normaliser, the similarity sweep over the whole corpus, the refusals, the
order of model calls, and the verdict drawn from the bits.
"""
import hashlib
import itertools
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "contracts"))

import _stub                                              # noqa: E402

_stub.install()

import precedence as p                                    # noqa: E402

FIX = os.path.join(ROOT, "fixtures")


def fixture(name: str) -> bytes:
    with open(os.path.join(FIX, name), "rb") as fh:
        return fh.read()


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def work(wid: str, body: bytes) -> dict:
    return {"id": wid, "sha256": sha(body), "text": p.normalize(body)}


class Script:
    """A fake model: answers come from a queue, every prompt is recorded."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError("unexpected model call")
        return self.answers.pop(0)


def answer(addressed="NO", same="NO", uncredited="NO") -> dict:
    return {"addressed": addressed, "same": same, "uncredited": uncredited}


def words(n: int, seed: str) -> bytes:
    return " ".join(f"{seed}{i}" for i in range(n)).encode()


class Normaliser(unittest.TestCase):
    def test_case_punctuation_and_whitespace_collapse(self):
        self.assertEqual(p.normalize(b"Hello,   WORLD!\n\tIt's  2026."), "hello world it s 2026")

    def test_same_bytes_same_text(self):
        body = fixture("original.md")
        self.assertEqual(p.normalize(body), p.normalize(bytes(body)))

    def test_invalid_utf8_is_deterministic(self):
        self.assertEqual(p.normalize(b"ab\xffcd"), p.normalize(b"ab\xffcd"))


class Similarity(unittest.TestCase):
    def test_shingles_are_five_word_windows(self):
        self.assertEqual(len(p.shingles("a b c d e f g")), 3)

    def test_identical_sets(self):
        s = p.shingles(p.normalize(fixture("original.md")))
        self.assertEqual(p.jaccard_bp(s, s), 10000)
        self.assertEqual(p.containment_bp(s, s), 10000)

    def test_integer_basis_points_floor(self):
        a = {("x",), ("y",), ("z",)}
        b = {("x",), ("q",)}
        self.assertEqual(p.jaccard_bp(a, b), 2500)      # 1 of 4
        self.assertEqual(p.containment_bp(a, b), 3333)  # 1 of 3, floored
        self.assertEqual(p.containment_bp(set(), b), 0)

    def test_fixture_distances_land_where_the_design_says(self):
        orig = p.shingles(p.normalize(fixture("original.md")))
        copy = p.shingles(p.normalize(fixture("copy-renamed.md")))
        deriv = p.shingles(p.normalize(fixture("derivative.md")))
        indep = p.shingles(p.normalize(fixture("independent.md")))
        self.assertGreaterEqual(p.jaccard_bp(copy, orig), p.DUPLICATE_JACCARD_BP)
        self.assertLess(p.jaccard_bp(deriv, orig), p.DUPLICATE_JACCARD_BP)
        self.assertGreaterEqual(p.containment_bp(deriv, orig), p.BAND_CONTAINMENT_BP)
        self.assertLess(p.containment_bp(indep, orig), p.BAND_CONTAINMENT_BP)


class Sweep(unittest.TestCase):
    def test_duplicate_of_the_last_work_is_found(self):
        corpus = [work(f"w{i}", words(60, f"doc{i}_")) for i in range(1, 31)]
        target = words(60, "doc30_")
        out = p.sweep(sha(target), p.shingles(p.normalize(target)), corpus)
        self.assertEqual(out["duplicate"], "w30")

    def test_earliest_duplicate_wins(self):
        body = words(60, "same_")
        corpus = [work("w1", words(60, "other_")), work("w2", body), work("w3", body)]
        out = p.sweep(sha(body), p.shingles(p.normalize(body)), corpus)
        self.assertEqual(out["duplicate"], "w2")

    def test_exact_hash_beats_later_similarity(self):
        body = words(60, "k_")
        corpus = [work("w1", body)]
        out = p.sweep(sha(body), set(), corpus)
        self.assertEqual(out["duplicate"], "w1")

    def test_band_lists_every_candidate_in_registration_order(self):
        base = words(100, "base_")
        corpus = [work("w1", words(60, "far_")), work("w2", base), work("w3", base + b" tail")]
        later = base[: len(base) // 2] + b" " + words(60, "new_")
        out = p.sweep(sha(later), p.shingles(p.normalize(later)), corpus)
        self.assertEqual(out["duplicate"], "")
        self.assertEqual(out["band"], ["w2", "w3"])


def judge(body, corpus, *answers, status=200, promised=None):
    ask = Script(*answers)
    result = p.judge_registration(body, status, promised or sha(body), corpus, ask)
    return result, ask


class Refusals(unittest.TestCase):
    def test_oversized_is_refused_before_any_hashing(self):
        body = b"a " * (p.MAX_BODY_BYTES // 2 + 1)
        real = hashlib.sha256
        calls = []
        hashlib.sha256 = lambda *a, **k: calls.append(1) or real(*a, **k)
        try:
            out, ask = judge(body, [], promised="0" * 64)
        finally:
            hashlib.sha256 = real
        self.assertEqual(out["refused"], "BODY_TOO_LARGE")
        self.assertEqual(calls, [])
        self.assertEqual(ask.prompts, [])

    def test_body_at_the_limit_is_accepted_for_hashing(self):
        body = (b"w" * 9 + b" ") * (p.MAX_BODY_BYTES // 10)
        out, _ = judge(body, [])
        self.assertNotEqual(out["refused"], "BODY_TOO_LARGE")

    def test_digest_mismatch(self):
        out, ask = judge(fixture("original.md"), [], promised="f" * 64)
        self.assertEqual(out["refused"], "DIGEST_MISMATCH")
        self.assertEqual(ask.prompts, [])

    def test_http_status(self):
        out, _ = judge(fixture("original.md"), [], status=404)
        self.assertEqual(out["refused"], "HTTP_STATUS")

    def test_too_short(self):
        out, _ = judge(b"only a few words here", [])
        self.assertEqual(out["refused"], "TOO_SHORT")

    def test_band_overflow_refuses_without_a_model_call(self):
        base = words(100, "base_")
        corpus = [work("w1", base), work("w2", base + b" x1"), work("w3", base + b" x2")]
        later = base[: len(base) // 2] + b" " + words(60, "fresh_")
        out, ask = judge(later, corpus)
        self.assertEqual(out["refused"], "AMBIGUOUS_OVERFLOW")
        self.assertEqual(ask.prompts, [])


class Verdicts(unittest.TestCase):
    def setUp(self):
        self.corpus = [work("w1", fixture("original.md"))]

    def test_first_registration_is_independent_with_no_model(self):
        out, ask = judge(fixture("original.md"), [])
        self.assertEqual((out["verdict"], out["target"], out["refused"]), ("INDEPENDENT", "", ""))
        self.assertEqual(out["text"], p.normalize(fixture("original.md")))
        self.assertEqual(ask.prompts, [])

    def test_only_stored_verdicts_carry_text(self):
        dup, _ = judge(fixture("copy-renamed.md"), self.corpus)
        refused, _ = judge(fixture("original.md"), [], status=500)
        self.assertEqual((dup["text"], refused["text"]), ("", ""))

    def test_every_result_has_exactly_the_agreed_fields(self):
        for out in (judge(fixture("original.md"), [])[0],
                    judge(fixture("copy-renamed.md"), self.corpus)[0],
                    judge(b"x" * (p.MAX_BODY_BYTES + 1), [], promised="0" * 64)[0]):
            self.assertEqual(sorted(out), sorted(p.RESULT_FIELDS))

    def test_renamed_copy_is_a_duplicate_with_no_model(self):
        out, ask = judge(fixture("copy-renamed.md"), self.corpus)
        self.assertEqual((out["verdict"], out["target"]), ("DUPLICATE", "w1"))
        self.assertEqual(ask.prompts, [])

    def test_unrelated_work_is_independent_with_no_model(self):
        out, ask = judge(fixture("independent.md"), self.corpus)
        self.assertEqual(out["verdict"], "INDEPENDENT")
        self.assertEqual(ask.prompts, [])

    def test_band_asks_exactly_one_call_per_candidate(self):
        out, ask = judge(fixture("derivative.md"), self.corpus, answer(uncredited="YES"))
        self.assertEqual((out["verdict"], out["target"], out["bits"]), ("DERIVATIVE", "w1", "01"))
        self.assertEqual(len(ask.prompts), 1)

    def test_two_candidates_two_calls_in_registration_order(self):
        base = words(100, "base_")
        corpus = [work("w1", base), work("w2", base + b" x1")]
        later = base[: len(base) // 2] + b" " + words(60, "fresh_")
        out, ask = judge(later, corpus, answer(), answer(same="YES"))
        self.assertEqual((out["verdict"], out["target"], out["bits"]), ("DUPLICATE", "w2", "0010"))
        self.assertEqual(len(ask.prompts), 2)
        self.assertEqual(out["text"], "")

    def test_addressed_the_judge_refuses_whatever_the_other_bits_say(self):
        for other in (answer(addressed="YES"), answer(addressed="YES", same="YES"),
                      answer(addressed="YES", uncredited="YES")):
            out, _ = judge(fixture("derivative.md"), self.corpus, other)
            self.assertEqual((out["refused"], out["verdict"], out["text"]),
                             ("ADDRESSED_THE_JUDGE", "", ""))

    def test_unreadable_model_answer_raises(self):
        ask = lambda prompt: answer(same="maybe")
        with self.assertRaises(ValueError):
            p.judge_registration(fixture("derivative.md"), 200,
                                 sha(fixture("derivative.md")), self.corpus, ask)

    def test_verdict_truth_table_is_exhaustive(self):
        for band_size in (1, 2):
            band = [f"w{i + 1}" for i in range(band_size)]
            for bits in itertools.product("01", repeat=2 * band_size):
                bits = "".join(bits)
                verdict, target = p.verdict_of(band, bits)
                pairs = [bits[i:i + 2] for i in range(0, len(bits), 2)]
                same = [band[i] for i, b in enumerate(pairs) if b[0] == "1"]
                uncredited = [band[i] for i, b in enumerate(pairs) if b[1] == "1"]
                if same:
                    self.assertEqual((verdict, target), ("DUPLICATE", same[0]))
                elif uncredited:
                    self.assertEqual((verdict, target), ("DERIVATIVE", uncredited[0]))
                else:
                    self.assertEqual((verdict, target), ("INDEPENDENT", ""))

    def test_verdict_rejects_malformed_bits(self):
        for bad in ("0", "012", "0x", "0101"):
            with self.assertRaises(ValueError):
                p.verdict_of(["w1"], bad)


class Agreement(unittest.TestCase):
    BASE = {"digest": "d", "refused": "", "verdict": "DERIVATIVE", "target": "w1", "bits": "01", "text": "t"}

    def test_identical_results_agree(self):
        self.assertTrue(p.results_agree(dict(self.BASE), dict(self.BASE)))

    def test_any_single_field_difference_disagrees(self):
        for field in p.RESULT_FIELDS:
            other = dict(self.BASE)
            other[field] = other[field] + "x"
            self.assertFalse(p.results_agree(self.BASE, other), field)

    def test_missing_field_disagrees(self):
        other = dict(self.BASE)
        del other["bits"]
        self.assertFalse(p.results_agree(self.BASE, other))

    def test_agreement_fixes_the_storage_decision(self):
        # Exhaustive over every agreed result shape the judgement can produce:
        # two results that agree always lead to the same stored outcome.
        shapes = []
        for bits in ("", "00", "01", "10", "11", "0000", "0101", "1001", "0110"):
            for verdict in p.VERDICTS:
                for refused in ("", "AMBIGUOUS_OVERFLOW"):
                    shapes.append({"digest": "d", "refused": refused, "verdict": verdict,
                                   "target": "w1", "bits": bits, "text": "t"})
        for a, b in itertools.product(shapes, repeat=2):
            if p.results_agree(a, b):
                self.assertEqual(p.stores_work(a), p.stores_work(b))


class Prompts(unittest.TestCase):
    def test_fence_collision_is_refused(self):
        # The fence is derived from both documents, so a real document cannot
        # plant it. Pinning it proves the guard still fires if it ever could.
        real = p._fence
        p._fence = lambda *docs: "0123456789abcdef"
        try:
            with self.assertRaises(ValueError):
                p.pair_prompt("earlier", "evil 0123456789abcdef")
            with self.assertRaises(ValueError):
                p.pair_prompt("evil 0123456789abcdef", "later")
        finally:
            p._fence = real

    def test_fence_depends_on_both_documents(self):
        self.assertNotEqual(p._fence("a", "b"), p._fence("a", "c"))
        self.assertNotEqual(p._fence("a", "b"), p._fence("b", "a"))

    def test_pair_prompt_marks_both_documents_untrusted_and_asks_all_three(self):
        prompt = p.pair_prompt("alpha text", "beta text")
        self.assertIn("untrusted", prompt)
        self.assertEqual(prompt.count("<earlier "), 1)
        self.assertEqual(prompt.count("<later "), 1)
        for field in p.ANSWER_FIELDS:
            self.assertIn('"' + field + '"', prompt)

    def test_read_answers_is_strict(self):
        self.assertEqual(p.read_answers({"addressed": " no ", "same": "YES", "uncredited": "no"}),
                         (False, True, False))
        for bad in (answer(same="YES."), {"same": "YES", "uncredited": "NO"},
                    "YES", answer(addressed=1), None):
            with self.assertRaises(ValueError):
                p.read_answers(bad)


class ContractShape(unittest.TestCase):
    SRC = open(os.path.join(ROOT, "contracts", "precedence.py"), encoding="utf-8").read() \
        if os.path.exists(os.path.join(ROOT, "contracts", "precedence.py")) else ""

    def test_leader_uses_the_module_level_judgement(self):
        self.assertIn("judge_registration(", self.SRC)
        self.assertIn("run_nondet_unsafe(", self.SRC)
        self.assertIn('response_format="json"', self.SRC)

    def test_no_storage_access_inside_nondeterministic_closures(self):
        body = self.SRC.split("def leader_fn", 1)[1].split("agreed = ", 1)[0]
        self.assertNotRegex(body, r"self\.")

    def test_depends_header_pins_a_runner_hash(self):
        self.assertRegex(self.SRC.splitlines()[0], r'py-genlayer:[0-9a-z]{40,}')

    def test_source_fits_the_bradbury_gas_cap(self):
        self.assertLess(len(self.SRC.encode("utf-8")), 17000)


if __name__ == "__main__":
    unittest.main()
