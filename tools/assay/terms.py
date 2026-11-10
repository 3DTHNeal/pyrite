"""Specialist terms need a source. A capitalized term, acronym or CamelCase name that no source uses is likely
invented, and a term that only a reference text uses (such as the posting a draft answers) is something asked for,
not evidence that it's true."""
import re
from collections.abc import Iterable

WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:[-/.][A-Za-z0-9+#]+)*\+*")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")
# Capitalized words of any English prose: they name no skill.
CALENDAR_WORDS = frozenset({
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec", "monday", "tuesday", "wednesday", "thursday", "friday",
})


def vocabulary(text: str) -> set[str]:
    """The words a text uses, in lowercase. The parts of a compound are words it uses too: GPU-batched names GPU, and
    CI/CD names CI."""
    words = WORD.findall(text)
    whole = {w.lower().strip("+") for w in words} | {w.lower() for w in words}
    return whole | {part.lower().strip("+") for w in words for part in re.split(r"[-/]", w) if part}


def is_acronym_or_camel(word: str) -> bool:
    return any(c.isupper() for c in word[1:])


def known_term(low: str, known: set[str]) -> bool:
    """Whether a term, in lowercase, is one the sources use, or a compound of ones they use: Cross-Team names nothing
    new when they write both words."""
    parts = [part.strip("+") for part in re.split(r"[-/]", low) if part]
    return low in known or (len(parts) > 1 and all(part in known for part in parts))


def novel_terms(text: str, known: set[str], first_words: Iterable[str] = ()) -> list[str]:
    """Capitalized terms that aren't in `known`, the lowercase words the sources use plus any allowed anyway: likely
    invented. The first word of a sentence is capitalized anyway, so there only an acronym, CamelCase, or one of
    `first_words` (such as a title, "Director") stands out."""
    first = set(first_words)
    novel = []
    for sentence in SENTENCE.split(text):
        words = WORD.findall(sentence)
        for index, word in enumerate(words):
            if not (is_acronym_or_camel(word) or (word[0].isupper() and (index or word.lower() in first))):
                continue
            if known_term(word.lower().strip("+"), known):
                continue
            if word not in novel:
                novel.append(word)
    return novel


def named_terms(reference: str) -> set[str]:
    """Names a reference text uses for tools and skills, in lowercase: capitalized mid-sentence or an acronym, and never
    written in lowercase."""
    named, lowercase = set(), set()
    for sentence in SENTENCE.split(reference):
        for index, word in enumerate(WORD.findall(sentence)):
            if word.islower():
                lowercase.add(word.strip("+"))
            elif is_acronym_or_camel(word) or (index and word[0].isupper() and len(word) >= 4):
                named.add(word.lower().strip("+"))
    return named - lowercase


def borrowed_terms(text: str, reference: str, known: set[str], already: list[str]) -> list[str]:
    """Terms of the reference text that the draft uses capitalized, including to open a sentence or bullet, where the
    capitals check alone can't tell a name from a verb. `already` are terms reported as novel, which aren't named twice.

    Lowercase words are left alone: a posting's "Gives Back" program mustn't block "came back".
    """
    wanted = {term for term in named_terms(reference) - {word.lower().strip("+") for word in already} if not known_term(term, known)}
    borrowed = []
    for word in WORD.findall(text):
        if word[0].isupper() and word.lower().strip("+") in wanted and word not in borrowed:
            borrowed.append(word)
    return borrowed
