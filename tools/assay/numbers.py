"""Numbers stay as measured. Every number, percentage, multiple and spelled-out number in a draft must be one the
sources state, with the same value and scale. Nothing is worked out: 42 s to 9 s doesn't approve "79%"."""
import re
from decimal import Decimal, InvalidOperation

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


def number_errors(label: str, body: str, known: str, where: str) -> list[str]:
    """Numbers, percentages, spelled-out numbers and multiples in body that the known text doesn't hold. `where` ends
    each message, saying what they're missing from, such as "not in the fact bank"."""
    errors = []
    invented_pct = sorted(percents(body) - percents(known))
    if invented_pct:
        errors.append(f"{label} has percentages {where}: {', '.join(p + '%' for p in invented_pct)}")
    invented = sorted(numbers(body) - numbers(known))
    if invented:
        errors.append(f"{label} has numbers {where}: {', '.join(invented)}")
    # Both sides are read the same way. The "million" of "$1.5 million" is part of that number in the sources as it
    # is in a draft, so it doesn't approve "five million" of anything.
    words = sorted(spelled(body) - spelled(known))
    if words:
        errors.append(f"{label} spells out numbers {where}: {', '.join(words)}. Write numbers as digits, as measured.")
    multiples = sorted(({m.group(0).lower() for m in MULTIPLE.finditer(body)} - _phrases(MULTIPLE, known))
                       | {f"{value(m.group(1))}x" for m in NUMERIC_MULTIPLE.finditer(body)}
                       - {f"{value(m.group(1))}x" for m in NUMERIC_MULTIPLE.finditer(known)})
    if multiples:
        errors.append(f"{label} claims a multiple {where}: {', '.join(multiples)}. Give the measured number instead.")
    return errors
