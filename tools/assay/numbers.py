"""Numbers stay as measured. Every number, percentage, multiple and spelled-out number in a draft must be one the
sources state, with the same value and scale. Nothing is worked out: 42 s to 9 s doesn't approve "79%".

`number_errors` gives the verdict as sentences and `number_findings` gives it as data, each finding with its place in
the text. Both take a `Policy`. The default, `EXACT`, is the rule above. `MEASURED` is for evidence nobody wrote as a
list of facts, such as a filing whose tables state their unit once in a heading: it accepts a figure the evidence
gives more exactly or at another scale, and still nothing is worked out."""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .findings import Finding

# A number keeps its scale: $3M isn't the 3 the fact bank measured, and 212K tests aren't 212. Each reads as its value,
# so 1.5M and 1,500,000 are the same number. A scale word counts in any case and after a space: 3 Million, 3 bn.
# A lowercase m, or a letter after a space, is a scale only after a currency sign, as in $3m, $3 MM or $3 mil: on its own
# 30m is as often minutes, 5 mil a film thickness and 300 K a temperature.
# A number may start at its decimal point, as in .83 seconds.
NUMBER = re.compile(
    r"(?:(?P<money>[$€£])\s?|(?<![\w.]))(?P<digits>\d[\d,]*(?:\.\d+)?|\.\d+)"
    r"(?:\s?(?P<word>(?i:thousand|million|billion|trillion|bn))\b|(?P<letter>K|k|M|MM|B)\b"
    r"|(?(money)\s?(?P<cash>(?i:mm|mil|mn|k|m|b))\b|(?!)))?"
)
SCALE = {"thousand": 3, "k": 3, "million": 6, "m": 6, "mm": 6, "mil": 6, "mn": 6, "billion": 9, "b": 9, "bn": 9, "trillion": 12}
# A percentage spelled out is still a percentage, and so is a change in percentage points.
PERCENT = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(?:%|percent(?:age)?(?:\s+points?)?\b|per\s?cent\b|pct\b|pp\b|p\.p\.)", re.I
)
# Multiples, fractions and orders of magnitude claimed in words are measurements too, in any form of the word: doubled,
# doubling, twice as fast, cut in half, by a third. Words that only look like one are left alone: a third launch, the
# second half of the year, both halves of a job, double-precision, half-duplex.
MULTIPLE = re.compile(
    r"\b(?:(?:doubl|tripl|quadrupl)(?:ed|es|ing)|halv(?:ed|ing)|(?:double|triple|quadruple)\s+(?:the|its|their|our)"
    r"|twice\s+(?:as|the)|thrice|(?:in|by)\s+half(?!-)|half\s+(?:the|as)"
    r"|(?:a|one)\s+(?:third|quarter|fifth|tenth)\s+(?:of|less|more|fewer|faster|slower|lower|higher)"
    r"|by\s+(?:a|one)\s+(?:third|quarter|fifth|tenth)|(?:two|three|four)[- ](?:thirds|fifths)|three-quarters"
    r"|(?:two|three|four|five|six|seven|eight|nine|ten|hundred|thousand)[- ]?fold"
    r"|(?:double|triple)[- ]digits?|(?:five|six|seven|eight|nine|ten)[- ]figures?|orders? of magnitude)\b",
    re.I,
)
# A multiple in digits, however it's written: 8x, 2.5×, 3-fold, 3 times faster. It's a measurement of its own, whatever
# counts the fact bank holds, and each form reads as the same multiple.
NUMERIC_MULTIPLE = re.compile(
    r"(?<![\w.,])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s?[x×](?!\w)|[- ]?fold\b"
    r"|\s+times\s+(?:as|the|faster|slower|more|less|fewer|higher|lower|better|greater|larger|smaller|quicker)\b)",
    re.I,
)
# Numbers written as words slip past a check on digits. One to ten are too common in prose to police.
NUMBER_WORD = re.compile(
    r"\b(?:eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundreds?|thousands?|millions?|billions?|dozens?)\b",
    re.I,
)


def value(digits: str, scale: str = "") -> str:
    """A number as one canonical string: 1,500,000 and 1.5M are both 1500000, and 4.0 is 4."""
    digits = digits.replace(",", "")
    try:
        number = Decimal(digits).scaleb(SCALE.get(scale.lower(), 0) if scale else 0)
    except InvalidOperation:
        return digits
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def numbers(text: str) -> set[str]:
    """The numbers a text states, percentages aside: a number the sources have only as a percentage counts nothing."""
    return {value(m.group("digits"), m.group("word") or m.group("letter") or m.group("cash") or "")
            for m in NUMBER.finditer(PERCENT.sub(" ", text))}


def percents(text: str) -> set[str]:
    return {value(m.group(1)) for m in PERCENT.finditer(text)}


def spelled(text: str) -> set[str]:
    """Numbers written as words, apart from a scale word that follows digits, which is part of that number."""
    return {match.group(0).lower() for match in NUMBER_WORD.finditer(NUMBER.sub(" ", text))}


def _phrases(pattern: re.Pattern[str], text: str) -> set[str]:
    return {m.group(0).lower() for m in pattern.finditer(text)}


@dataclass(frozen=True)
class Quantity:
    """One number as a text states it, and where."""
    # "percent", "number", "spelled" (a number written as a word) or "multiple" (8x, or one claimed in words).
    kind: str
    # The form the checks compare. For a number or a percentage, what `value` gives: 1.5M and 1,500,000 are both
    # "1500000". For a spelled-out number, the word. For a multiple, "8x" or the phrase, in lowercase.
    value: str
    # The words as the text has them, and where: text[start:end].
    text: str
    start: int
    end: int
    # The number itself, for the kinds that have one, and the power of ten its last written digit stands for:
    # 551.1 is to the tenth (-1), and $440.1M is to the hundred thousand (5).
    amount: Decimal | None = None
    exponent: int = 0
    # How many digits it's written to, leading zeros aside: 551.1 has 4, 0.55 has 2 and a lone 2 has 1.
    figures: int = 0


def _blanked(pattern: re.Pattern[str], text: str) -> tuple[str, list[int]]:
    """The text with each match replaced by one space, as `pattern.sub(" ", text)` gives it, and for each character
    of the result the place it had in the text. One more place is given at the end, for a match that runs to it."""
    pieces: list[str] = []
    places: list[int] = []
    last = 0
    for match in pattern.finditer(text):
        pieces += [text[last:match.start()], " "]
        places += [*range(last, match.start()), match.start()]
        last = match.end()
    pieces.append(text[last:])
    places += [*range(last, len(text)), len(text)]
    return "".join(pieces), places


def _amount(digits: str, scale: str = "") -> tuple[Decimal | None, int, int]:
    """A number's value, the power of ten of its last written digit, and how many digits it's written to. For digits
    that aren't a number, (None, 0, 0)."""
    digits = digits.replace(",", "")
    power = SCALE.get(scale.lower(), 0) if scale else 0
    try:
        amount = Decimal(digits).scaleb(power)
    except InvalidOperation:
        return None, 0, 0
    return amount, power - (len(digits.split(".")[1]) if "." in digits else 0), len(digits.replace(".", "").lstrip("0"))


def quantities(text: str) -> list[Quantity]:
    """Every number a text states, of each kind the checks know, in the order they stand. `numbers`, `percents` and
    `spelled` are views of this: the same patterns, read the same way, with each one's place kept."""
    found = []
    for m in PERCENT.finditer(text):
        found.append(Quantity("percent", value(m.group(1)), m.group(0), m.start(), m.end(), *_amount(m.group(1))))
    without_percents, places = _blanked(PERCENT, text)
    for m in NUMBER.finditer(without_percents):
        scale = m.group("word") or m.group("letter") or m.group("cash") or ""
        start, end = places[m.start()], places[m.end() - 1] + 1
        found.append(Quantity("number", value(m.group("digits"), scale), text[start:end], start, end,
                              *_amount(m.group("digits"), scale)))
    without_numbers, places = _blanked(NUMBER, text)
    for m in NUMBER_WORD.finditer(without_numbers):
        start, end = places[m.start()], places[m.end() - 1] + 1
        found.append(Quantity("spelled", m.group(0).lower(), text[start:end], start, end))
    for m in MULTIPLE.finditer(text):
        found.append(Quantity("multiple", m.group(0).lower(), m.group(0), m.start(), m.end()))
    for m in NUMERIC_MULTIPLE.finditer(text):
        found.append(Quantity("multiple", f"{value(m.group(1))}x", m.group(0), m.start(), m.end(), *_amount(m.group(1))))
    return sorted(found, key=lambda q: (q.start, q.end, q.kind))


@dataclass(frozen=True)
class Policy:
    """How closely the evidence has to state a figure for it to support a claim.

    The default asks for the same value at the same scale, which is right where a person wrote the evidence for this
    purpose: $3M isn't the 3 a fact bank measured. Evidence that was written for something else states its unit once,
    in a table's heading, and rounds as it pleases. For that, `rounded` accepts a figure the evidence gives more
    exactly, and `shifts` lists the powers of ten its figures may be off by because their unit is said elsewhere.
    `bare_percent` accepts a percentage the evidence gives as a plain number, as a column headed "%" does.

    A figure is matched at another scale only when it's written to at least `figures` digits. A lone 2 would otherwise
    be supported by any 1,757 the evidence holds, read as thousands and rounded."""
    rounded: bool = False
    shifts: tuple[int, ...] = (0,)
    bare_percent: bool = False
    figures: int = 3


# The same value at the same scale. What every caller gets unless it asks otherwise.
EXACT = Policy()
# For evidence a person didn't write as a list of facts, such as a filing whose tables are in thousands.
MEASURED = Policy(rounded=True, shifts=(0, 3, 6, 9, -3, -6, -9), bare_percent=True)


@dataclass(frozen=True)
class Evidence:
    """What a text states, read once so that many claims can be judged against it."""
    numbers: frozenset[str]
    percents: frozenset[str]
    spelled: frozenset[str]
    multiples: frozenset[str]
    # The same numbers and percentages as amounts, in order of size, for a policy that allows more than an exact match.
    number_amounts: tuple[Decimal, ...] = ()
    percent_amounts: tuple[Decimal, ...] = ()


def evidence(known: str, amounts_too: bool = True) -> Evidence:
    """The numbers a known text holds, read the way a draft's are. The exact policy compares them as written and
    never looks at the amounts, so the check leaves those out when that's the policy it was given."""
    read = quantities(known) if amounts_too else []

    def amounts(kind: str) -> tuple[Decimal, ...]:
        return tuple(sorted({q.amount for q in read if q.kind == kind and q.amount is not None}))

    return Evidence(
        frozenset(numbers(known)), frozenset(percents(known)), frozenset(spelled(known)),
        frozenset(_phrases(MULTIPLE, known) | {f"{value(m.group(1))}x" for m in NUMERIC_MULTIPLE.finditer(known)}),
        amounts("number"), amounts("percent"))


def _holds(held: tuple[Decimal, ...], amount: Decimal, exponent: int, rounded: bool, shifts: tuple[int, ...]) -> bool:
    """Whether a sorted run of amounts holds one that is the claim's, at any of the scales allowed: the same value,
    or with `rounded`, one that rounds to it at the precision the claim is written to."""
    slack = Decimal(5).scaleb(exponent - 1) if rounded else Decimal(0)
    for shift in shifts:
        low, high = (amount - slack).scaleb(-shift), (amount + slack).scaleb(-shift)
        first, last = 0, len(held)
        while first < last:  # The first amount that isn't below `low`.
            middle = (first + last) // 2
            if held[middle] < low:
                first = middle + 1
            else:
                last = middle
        if first < len(held) and held[first] <= high:
            return True
    return False


def _supported(claim: Quantity, known: Evidence, policy: Policy) -> bool:
    if claim.kind == "percent":
        if claim.value in known.percents:
            return True
        if policy == EXACT or claim.amount is None:
            return False
        # A percentage has no unit to be stated elsewhere, so no shift of scale is tried.
        return (_holds(known.percent_amounts, claim.amount, claim.exponent, policy.rounded, (0,))
                or policy.bare_percent and _holds(known.number_amounts, claim.amount, claim.exponent, policy.rounded, (0,)))
    if claim.kind == "number":
        if claim.value in known.numbers:
            return True
        if policy == EXACT or claim.amount is None:
            return False
        shifts = policy.shifts if claim.figures >= policy.figures else tuple(shift for shift in policy.shifts if shift == 0)
        return _holds(known.number_amounts, claim.amount, claim.exponent, policy.rounded, shifts)
    # A spelled-out number and a multiple are matched as written, whatever the policy.
    return claim.value in (known.spelled if claim.kind == "spelled" else known.multiples)


def number_findings(body: str, known: str | Evidence, policy: Policy = EXACT) -> list[Finding]:
    """Each number, percentage, spelled-out number and multiple in body that the known text doesn't hold, in the order
    they stand. `known` is the evidence as text, or as `evidence` read it when many bodies are judged against it."""
    held = known if isinstance(known, Evidence) else evidence(known, amounts_too=policy != EXACT)
    return [Finding("numbers", q.kind, q.value, q.text, q.start, q.end)
            for q in quantities(body) if not _supported(q, held, policy)]


def number_errors(label: str, body: str, known: str | Evidence, where: str, policy: Policy = EXACT) -> list[str]:
    """Numbers, percentages, spelled-out numbers and multiples in body that the known text doesn't hold. `where` ends
    each message, saying what they're missing from, such as "not in the fact bank"."""
    found = number_findings(body, known, policy)

    def values(kind: str) -> list[str]:
        return sorted({finding.value for finding in found if finding.kind == kind})

    errors = []
    invented_pct = values("percent")
    if invented_pct:
        errors.append(f"{label} has percentages {where}: {', '.join(p + '%' for p in invented_pct)}")
    invented = values("number")
    if invented:
        errors.append(f"{label} has numbers {where}: {', '.join(invented)}")
    # Both sides are read the same way. The "million" of "$1.5 million" is part of that number in the sources as it
    # is in a draft, so it doesn't approve "five million" of anything.
    words = values("spelled")
    if words:
        errors.append(f"{label} spells out numbers {where}: {', '.join(words)}. Write numbers as digits, as measured.")
    multiples = values("multiple")
    if multiples:
        errors.append(f"{label} claims a multiple {where}: {', '.join(multiples)}. Give the measured number instead.")
    return errors
