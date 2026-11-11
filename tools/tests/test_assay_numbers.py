"""The assay's number check gives its verdict as data as well as sentences, and takes a policy for how closely the
evidence must state a figure. With the default policy nothing about a verdict may change: the first tests here hold the
new code to the check as it was, line for line."""
import functools
import re
import unittest
from decimal import Decimal

from support import CODE_ROOT, SOURCES

from assay import numbers
from assay.findings import Finding
from assay.numbers import EXACT, MEASURED, MULTIPLE, NUMERIC_MULTIPLE, Policy
from test_assay_probe import PROBES

# Lines that sit where the patterns meet: a percentage beside a currency sign, a scale word after a gap, digits that
# aren't a number, and each kind of multiple.
EDGES = [
    "Revenue of $440.1M, up 3.7% on 1,757 staff; costs doubled to twelve million, an 8x rise.",
    "$5%3m and 3 5% million and $ 50% 3M", "1,,2 and 1,2,3 and .83 seconds and 4.0", "$3 MM, $3 mil, 30m, 300 K, 5 mil",
    "up 2.5 percentage points, 40 pct, 12 per cent, 7pp", "3-fold, 3 times faster, 2.5× and 10x", "cut in half, by a third",
    "five million users and $1.5 million and hundreds of tests", "", "no numbers here", "100%", "%", "$", "x",
]


def corpus() -> list[str]:
    """Every line of the example workspace and the guide, each probe line, and the edge cases above."""
    lines = list(EDGES)
    for folder in ("example", "docs"):
        for path in sorted((CODE_ROOT / folder).rglob("*")):
            if path.suffix in (".md", ".txt", ".toml") and path.is_file():
                lines += path.read_text(encoding="utf-8").splitlines()
    lines += [line for _name, _gate, probes in PROBES for line, _first in probes]
    return list(dict.fromkeys(lines))


@functools.lru_cache(maxsize=4)
def known_as_it_was(known: str) -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    """What the check read from the known text, each part by the call it made. Kept apart only so that judging a
    thousand lines against one text reads that text once."""
    return (numbers.percents(known), numbers.numbers(known), numbers.spelled(known),
            {m.group(0).lower() for m in MULTIPLE.finditer(known)},
            {f"{numbers.value(m.group(1))}x" for m in NUMERIC_MULTIPLE.finditer(known)})


def errors_as_they_were(label: str, body: str, known: str, where: str) -> list[str]:
    """`numbers.number_errors` as it stood before findings and policies, kept here to compare the new one with."""
    known_percents, known_numbers, known_spelled, known_phrases, known_times = known_as_it_was(known)
    errors = []
    invented_pct = sorted(numbers.percents(body) - known_percents)
    if invented_pct:
        errors.append(f"{label} has percentages {where}: {', '.join(p + '%' for p in invented_pct)}")
    invented = sorted(numbers.numbers(body) - known_numbers)
    if invented:
        errors.append(f"{label} has numbers {where}: {', '.join(invented)}")
    words = sorted(numbers.spelled(body) - known_spelled)
    if words:
        errors.append(f"{label} spells out numbers {where}: {', '.join(words)}. Write numbers as digits, as measured.")
    multiples = sorted(({m.group(0).lower() for m in MULTIPLE.finditer(body)} - known_phrases)
                       | {f"{numbers.value(m.group(1))}x" for m in NUMERIC_MULTIPLE.finditer(body)} - known_times)
    if multiples:
        errors.append(f"{label} claims a multiple {where}: {', '.join(multiples)}. Give the measured number instead.")
    return errors


class ReadsEachNumberOnce(unittest.TestCase):
    def test_the_reader_finds_what_the_views_find(self):
        lines = corpus()
        self.assertGreater(len(lines), 500)
        for line in lines:
            read = numbers.quantities(line)
            with self.subTest(line=line[:80]):
                self.assertEqual({q.value for q in read if q.kind == "number"}, numbers.numbers(line))
                self.assertEqual({q.value for q in read if q.kind == "percent"}, numbers.percents(line))
                self.assertEqual({q.value for q in read if q.kind == "spelled"}, numbers.spelled(line))
                self.assertEqual({q.value for q in read if q.kind == "multiple"},
                                 {m.group(0).lower() for m in MULTIPLE.finditer(line)}
                                 | {f"{numbers.value(m.group(1))}x" for m in NUMERIC_MULTIPLE.finditer(line)})

    def test_each_one_knows_its_place(self):
        for line in corpus():
            for q in numbers.quantities(line):
                with self.subTest(line=line[:80], found=q.text):
                    self.assertEqual(line[q.start:q.end], q.text)
                    self.assertTrue(q.text.strip())
                    if q.kind == "spelled":
                        self.assertEqual(q.text.lower(), q.value)
                    elif q.kind in ("number", "percent"):
                        self.assertRegex(q.text, r"\d")

    def test_a_line_read_in_full(self):
        read = numbers.quantities(EDGES[0])
        self.assertEqual([(q.kind, q.value, q.text) for q in read], [
            ("number", "440100000", "$440.1M"), ("percent", "3.7", "3.7%"), ("number", "1757", "1,757"),
            ("multiple", "doubled", "doubled"), ("spelled", "twelve", "twelve"), ("spelled", "million", "million"),
            ("number", "8", "8"), ("multiple", "8x", "8x")])
        amounts = {q.text: (q.amount, q.exponent, q.figures) for q in read if q.amount is not None}
        self.assertEqual(amounts["$440.1M"], (Decimal("440100000"), 5, 4))  # Written to the hundred thousand, in four digits.
        self.assertEqual(amounts["3.7%"], (Decimal("3.7"), -1, 2))
        self.assertEqual(amounts["1,757"], (Decimal("1757"), 0, 4))
        self.assertEqual(numbers._amount("0.55", "B"), (Decimal("550000000"), 7, 2))

    def test_digits_that_arent_a_number_are_kept_as_written(self):
        odd = [q for q in numbers.quantities("part 1,,2") if q.kind == "number"]
        self.assertEqual([(q.value, q.amount) for q in odd], [("12", Decimal("12"))])
        self.assertEqual(numbers._amount("1.2.3"), (None, 0, 0))


class TheSameVerdictAsBefore(unittest.TestCase):
    def test_every_line_gets_the_sentences_it_got(self):
        lines = corpus()
        held = numbers.evidence(SOURCES)
        for line in lines:
            with self.subTest(line=line[:80]):
                was = errors_as_they_were("Draft", line, SOURCES, "not in the fact bank")
                self.assertEqual(numbers.number_errors("Draft", line, SOURCES, "not in the fact bank"), was)
                self.assertEqual(numbers.number_errors("Draft", line, held, "not in the fact bank"), was)

    def test_and_against_other_evidence_too(self):
        lines = corpus()
        for body, known in zip(lines, lines[1:] + lines[:1], strict=True):
            with self.subTest(body=body[:60], known=known[:60]):
                self.assertEqual(numbers.number_errors("Draft", body, known, "there"), errors_as_they_were("Draft", body, known, "there"))
        whole = "\n".join(lines)
        for body in EDGES:
            with self.subTest(body=body):
                self.assertEqual(numbers.number_errors("Draft", body, whole, "there"), errors_as_they_were("Draft", body, whole, "there"))

    def test_the_default_is_exact(self):
        known = "Raised 3 rounds."
        self.assertEqual(numbers.number_findings("Raised $3M.", known), numbers.number_findings("Raised $3M.", known, EXACT))
        self.assertEqual([f.value for f in numbers.number_findings("Raised $3M.", known)], ["3000000"])
        self.assertEqual(numbers.number_errors("Draft", "Raised $3M.", known, "not in the sources"),
                         ["Draft has numbers not in the sources: 3000000"])


class FindingsAreData(unittest.TestCase):
    KNOWN = "Cut build time from 42 s to 9 s with Bazel"

    def test_each_finding_says_what_it_is_and_where(self):
        body = "Cut build time by 79%, a 4.7x gain across 212K tests, from 42 s."
        found = numbers.number_findings(body, self.KNOWN)
        self.assertTrue(all(isinstance(f, Finding) and f.check == "numbers" for f in found))
        self.assertEqual([(f.kind, f.value, f.text) for f in found],
                         [("percent", "79", "79%"), ("number", "4.7", "4.7"), ("multiple", "4.7x", "4.7x"), ("number", "212000", "212K")])
        for f in found:
            self.assertEqual(body[f.start:f.end], f.text)

    def test_the_same_number_twice_is_two_findings_and_one_mention_in_the_sentence(self):
        body = "Shipped 83 builds, then 83 more."
        self.assertEqual(len(numbers.number_findings(body, self.KNOWN)), 2)
        self.assertEqual(numbers.number_errors("Draft", body, self.KNOWN, "not in the sources"), ["Draft has numbers not in the sources: 83"])

    def test_nothing_found_is_an_empty_list(self):
        self.assertEqual(numbers.number_findings("From 42 s to 9 s.", self.KNOWN), [])
        self.assertEqual(numbers.number_findings("", self.KNOWN), [])


class Measured(unittest.TestCase):
    """Evidence nobody wrote as a list of facts: a filing's table in thousands, with its unit said once."""
    FILING = ("In thousands of dollars.\nRevenue | 551,102 | 572,458\nGross margin | 41.2 | 44.9\n"
              "Goodwill was $101.6 million. Staff 1,757. Growth of 3.68% in services.")

    def flagged(self, body: str, policy: Policy) -> list[str]:
        return [f.text for f in numbers.number_findings(body, self.FILING, policy)]

    def test_the_exact_policy_wants_the_figure_as_written(self):
        self.assertEqual(self.flagged("Revenue was $551.1M, or 551.1.", EXACT), ["$551.1M", "551.1"])
        self.assertEqual(self.flagged("Goodwill $101.6M with 1,757 staff.", EXACT), [])

    def test_a_figure_the_evidence_gives_more_exactly_or_at_another_scale_is_supported(self):
        for body in ("Revenue was $551.1M.", "Revenue was 551.1.", "Revenue was 572.5 the year before.",
                     "Revenue of 551,102 thousand.", "Revenue of $551 million.", "Goodwill of 101.6.", "Services grew 3.7%."):
            with self.subTest(body):
                self.assertEqual(self.flagged(body, MEASURED), [])

    def test_a_percentage_may_be_a_plain_number_in_a_table(self):
        self.assertEqual(self.flagged("Gross margin was 41.2%.", EXACT), ["41.2%"])
        self.assertEqual(self.flagged("Gross margin was 41.2%.", MEASURED), [])
        self.assertEqual(self.flagged("Gross margin was 41.2%.", Policy(rounded=True)), ["41.2%"])

    def test_a_figure_the_evidence_doesnt_hold_is_still_flagged(self):
        for body, text in (("Revenue was $999.9M.", "$999.9M"), ("Revenue was 551.2.", "551.2"), ("Revenue was $552M.", "$552M"),
                           ("Services grew 3.6%.", "3.6%"), ("Margin of 41.25%.", "41.25%"), ("Staff of 1,758.", "1,758")):
            with self.subTest(body):
                self.assertEqual(self.flagged(body, MEASURED), [text])

    def test_nothing_is_worked_out_under_any_policy(self):
        # 572,458 less 551,102 is 21,356, and the fall is 3.7% of the earlier year. Neither is in the filing as such.
        self.assertEqual(self.flagged("Revenue fell by 21,356 thousand.", MEASURED), ["21,356 thousand"])
        self.assertEqual(self.flagged("Revenue fell 3.73%.", MEASURED), ["3.73%"])
        self.assertEqual(self.flagged("Revenue nearly doubled, to twelve times the staff, a 2x gain.", MEASURED), ["doubled", "twelve", "2", "2x"])

    def test_a_figure_too_round_to_tell_apart_isnt_matched_at_another_scale(self):
        # 1,757 read as thousands rounds to 2, and 551,102 thousand is about $0.55B. Neither says enough to be matched.
        self.assertEqual(self.flagged("A team of 2 and about $0.55B.", MEASURED), ["2", "$0.55B"])
        self.assertEqual(self.flagged("About $0.551B.", MEASURED), [])
        self.assertEqual(self.flagged("About $0.55B.", Policy(rounded=True, shifts=(0, 3), figures=2)), [])
        # At the evidence's own scale a short figure is matched as usual: 44.9 is about 45, though 1,757 isn't 1,760.
        self.assertEqual(self.flagged("Staff of 1,760 and a margin near 45.", Policy(rounded=True)), ["1,760"])
        self.assertEqual(self.flagged("A margin near 45.", MEASURED), [])

    def test_a_percentage_in_the_evidence_supports_no_plain_number(self):
        self.assertEqual(self.flagged("A team of 3.68 engineers.", MEASURED), ["3.68"])

    def test_the_policy_says_which_scales_and_whether_to_round(self):
        rounded_only = Policy(rounded=True)
        self.assertEqual(self.flagged("Revenue was 551.1.", rounded_only), ["551.1"])        # No shift of scale allowed,
        self.assertEqual(self.flagged("Goodwill of $101.6 million.", rounded_only), [])      # and none needed here.
        thousands_only = Policy(shifts=(0, 3))
        self.assertEqual(self.flagged("Revenue of $551,102,000.", thousands_only), [])       # 551,102 thousand, exactly,
        self.assertEqual(self.flagged("Revenue of $551.1M.", thousands_only), ["$551.1M"])   # but not rounded.

    def test_evidence_is_read_once_for_many_claims(self):
        held = numbers.evidence(self.FILING)
        self.assertIn(Decimal("551102"), held.number_amounts)
        self.assertEqual(list(held.number_amounts), sorted(held.number_amounts))
        for body in ("Revenue was $551.1M.", "Revenue was $999.9M.", "Margin 41.2%."):
            self.assertEqual(numbers.number_findings(body, held, MEASURED), numbers.number_findings(body, self.FILING, MEASURED))

    def test_sentences_come_from_the_same_findings(self):
        self.assertEqual(numbers.number_errors("Note", "Revenue was $551.1M and $999.9M.", self.FILING, "not in its source", MEASURED),
                         ["Note has numbers not in its source: 999900000"])


class TheLineBetweenTheTwo(unittest.TestCase):
    def test_the_pattern_for_a_percent_and_the_reader_agree_on_awkward_spacing(self):
        for line in EDGES:
            with self.subTest(line):
                blanked, places = numbers._blanked(numbers.PERCENT, line)
                self.assertEqual(blanked, numbers.PERCENT.sub(" ", line))
                self.assertEqual(len(places), len(blanked) + 1)
                self.assertEqual(places, sorted(places))
        self.assertTrue(re.search(r"\$\s3m", numbers._blanked(numbers.PERCENT, "$5%3m")[0]))


class NotMeasured(unittest.TestCase):
    """Digits a source writes without measuring anything. `MEASURED` sets them aside and `EXACT` reads them as before."""
    KINDS = [
        ("date", "Filed on 2025-03-31 by the board.", "2025-03-31"),
        ("date", "Filed on 31 March 2025 by the board.", "31 March 2025"),
        ("date", "Filed on Mar. 31, 2025 by the board.", "Mar. 31, 2025"),
        ("period", "Sales for 9M 2025 rose.", "9M"),  # Its year is set aside as a year.
        ("identifier", "Under Regulation 2023/1230 the plant was cleared.", "2023/1230"),
        ("identifier", "Solvent 7732-18-5 was used.", "7732-18-5"),
        ("unit label", "Revenue (in thousands of dollars) is shown.", "(in thousands of dollars)"),
        ("unit label", "Revenue (Millions) is shown.", "(Millions)"),
        ("year", "In 2024, the mill reopened.", "2024"),
    ]

    def found(self, body: str, policy: Policy, known: str = "") -> list[str]:
        return [f.text for f in numbers.number_findings(body, known, policy)]

    def test_each_kind_is_set_aside_under_measured(self):
        for kind, body, text in self.KINDS:
            with self.subTest(body):
                start = body.index(text)
                self.assertIn((kind, start, start + len(text)), numbers.not_measured(body, MEASURED))
                self.assertEqual(self.found(body, MEASURED), [])
                self.assertEqual(numbers.quantities(body, MEASURED), [])

    def test_and_read_as_before_under_exact(self):
        for _kind, body, _text in self.KINDS:
            with self.subTest(body):
                self.assertEqual(numbers.not_measured(body, EXACT), [])
                self.assertEqual(numbers.quantities(body, EXACT), numbers.quantities(body))
                self.assertEqual(numbers.number_errors("Draft", body, "", "there", EXACT), errors_as_they_were("Draft", body, "", "there"))
                self.assertTrue(self.found(body, EXACT))

    def test_the_default_sets_nothing_aside_across_the_corpus(self):
        for line in corpus():
            with self.subTest(line=line[:80]):
                self.assertEqual(numbers.quantities(line, EXACT), numbers.quantities(line))

    def test_nine_months_isnt_nine_million(self):
        body = "Revenue for 9M 2025 was $9M."
        self.assertEqual([(q.value, q.text) for q in numbers.quantities(body)], [("9000000", "9M"), ("2025", "2025"), ("9000000", "$9M")])
        self.assertEqual([(q.value, q.text) for q in numbers.quantities(body, MEASURED)], [("9000000", "$9M")])
        self.assertEqual(self.found(body, MEASURED, known="Revenue was 9,000,000 (in dollars)."), [])
        self.assertEqual(self.found("Revenue for 9M 2025 was $8M.", MEASURED, known="Revenue was 9,000."), ["$8M"])

    def test_an_accounting_negative_is_its_number(self):
        body = "Net loss was $(103,567) thousand."
        self.assertEqual(numbers.not_measured(body, MEASURED), [("negative", body.index("("), body.index(")") + 1)])
        read = numbers.quantities(body, MEASURED)
        self.assertEqual([(q.value, q.text) for q in read], [("103567000", "$(103,567) thousand")])
        self.assertEqual([(q.value, q.text) for q in numbers.quantities(body)], [("103567", "103,567"), ("thousand", "thousand")])
        self.assertEqual(self.found(body, MEASURED, known="Net loss | (103,567) | (98,210)"), [])
        self.assertEqual(self.found("Net loss was $(103,568) thousand.", MEASURED, known="Net loss | (103,567)"), ["$(103,568) thousand"])
        self.assertEqual([(q.kind, q.text) for q in numbers.quantities("Margin fell (12.5)% and (3.1)%.", MEASURED)],
                         [("percent", "(12.5)%"), ("percent", "(3.1)%")])
        # Brackets against a word or other digits keep apart what they keep apart, and are read as before.
        for body in ("See note(3).", "Items (3)(4) and (5)6."):
            with self.subTest(body):
                self.assertEqual(numbers.not_measured(body, MEASURED), [])
                self.assertEqual(numbers.quantities(body, MEASURED), numbers.quantities(body))

    def test_findings_keep_their_place_in_the_text_as_written(self):
        body = "On 31 March 2025, (in thousands) revenue was $(551,102) and 2024 staff 1,757 at a 41.2% margin."
        found = numbers.number_findings(body, "", MEASURED)
        self.assertEqual([f.text for f in found], ["$(551,102)", "1,757", "41.2%"])
        for f in found:
            self.assertEqual(body[f.start:f.end], f.text)
        self.assertEqual([body[start:end] for _kind, start, end in numbers.not_measured(body, MEASURED)],
                         ["31 March 2025", "(in thousands)", "(551,102)", "2024"])

    def test_a_year_written_as_an_amount_is_still_an_amount(self):
        for body, text in (("Spent $2050 on parts.", "$2050"), ("Grew 2000% in a decade.", "2000%"),
                           ("A budget of 1950 million.", "1950 million"), ("A 2020-fold rise.", "2020-fold")):
            with self.subTest(body):
                self.assertEqual(numbers.not_measured(body, MEASURED), [])
                self.assertIn(text, self.found(body, MEASURED))
        self.assertEqual(self.found("Staff of 2,024 and 2024.5 tonnes.", MEASURED), ["2,024", "2024.5"])

    def test_evidence_is_read_the_same_way(self):
        # A date in the evidence supports no number, as a date in the text judged is no claim.
        self.assertEqual(self.found("A team of 31.", EXACT, known="Filed 31 March 2025."), [])
        self.assertEqual(self.found("A team of 31.", MEASURED, known="Filed 31 March 2025."), ["31"])
        held = numbers.evidence("Filed 31 March 2025. Loss $(4,120) thousand.", policy=MEASURED)
        self.assertEqual(held.numbers, frozenset({"4120000"}))
        self.assertEqual(numbers.number_findings("Loss of $4.12M.", held, MEASURED), [])

    def test_a_policy_names_the_kinds_it_sets_aside(self):
        years_only = Policy(set_aside=("year",))
        body = "On 2025-03-31, in 2024, (103,567) thousand."
        self.assertEqual([kind for kind, _start, _end in numbers.not_measured(body, years_only)], ["year", "year"])
        self.assertEqual([q.text for q in numbers.quantities(body, years_only) if q.kind == "number"], ["03", "31,", "103,567"])
        self.assertEqual([kind for kind, _start, _end in numbers.not_measured(body, Policy(negatives=True))], ["negative"])
        self.assertEqual(set(MEASURED.set_aside), set(numbers.NOT_MEASURED))
        self.assertTrue(MEASURED.negatives)
        self.assertEqual((EXACT.set_aside, EXACT.negatives), ((), False))


if __name__ == "__main__":
    unittest.main()
