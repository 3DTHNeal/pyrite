"""What a check found, as data. A caller that only needs sentences gets them from each check's `*_errors` function,
which is built on this. One that stores results, shows them in a table or points at the place in the text reads these
instead of taking a sentence apart."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    """One thing in a text that its evidence doesn't support."""
    # The check that found it, such as "numbers".
    check: str
    # What it is within that check, such as "percent" or "multiple".
    kind: str
    # What was found, in the one form the check compares: 1.5M and 1,500,000 are both "1500000".
    value: str
    # The words as the text has them, and where: text[start:end].
    text: str
    start: int
    end: int
