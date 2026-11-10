"""Unsupported claims. A claim the sources say isn't true is blocked wherever a draft makes it, and a sentence may name
one only to deny it: "I have not led that". A negative that praises the record ("never missed an X audit"), or one that
says the opposite of what it seems to ("no stranger to X"), denies nothing.

Each unsupported claim is found by a pattern. The patterns, and the words that open a denial (`disclaimers`), are
written by a person beside the fact bank, so the rules and the facts are reviewed together.
"""
import re
from typing import Any

from .text import matchable

# A negative only disclaims what follows it in the same clause. "Not only" is no negative at all, and neither is one
# that praises the record: "never failed an X audit", "not a single X finding", "without a single X nonconformance".
# Nor is one that says the opposite of what it seems to: "no stranger to X", "not new to X", "no shortage of X",
# "without question", or two that cancel, as in "not a day went by without X".
NOT_A_NEGATIVE = re.compile(
    r"(?:\b(?:not|no|never|without)|n['’]t)\s+(?:only|just|merely|less|fewer|a\s+single|fail\w*|miss\w*|lost|los[ei]\w*"
    r"|stranger|new|shortage|lack|far|question|doubt|exception|equal|peer|rival|unfamiliar)\b"
    r"|\b(?:not|no|never|hardly|rarely)\b[^;,:()]{0,60}?\bwithout\b",
    re.I,
)
# Punctuation and joining words start a new clause, so "With no added headcount, cut defects by 83%" denies nothing.
# So does a new subject: in "With no budget I led X" the negative is about the budget, not X.
CLAUSE_BREAK = re.compile(
    r"[;,:()]|\s[-–]\s|—|\b(?:but|however|although|though|whereas|while|and|after|before|when|which|who|where|since|because|then"
    r"|I|we)\b",
    re.I,
)
# A denial sits right before the claim it denies: "I have not yet worked under X", "no X experience".
# A negative further back is about something else: "Never missed a milestone leading X" is a claim of X.
DENIAL_REACH = 3
FIRST_PERSON_DENIAL = re.compile(
    r"\bI\s+(?:have|had|do|did|am|was|would|could|can|will)\s+(?:not|never)\b|\bI\s+have\s+yet\s+to\b|\bI\s+never\b"
    r"|\bI\s+(?:haven|hadn|don|didn|wasn|couldn|wouldn|won|can)['’]t\b|\bI['’]ve\s+(?:not|never)\b"
)
# A first-person denial after the claim counts only when it points back at it: "...and I have not done it", "...I haven't."
# "Led X, and I never missed a deadline" denies the deadline, not X.
REFERS_BACK = re.compile(r"(?:\s+[\w'’]+){0,4}?\s+(?:it|that|this|them|one|so|either|any|yet)\b|\W*$", re.I)
# Some negatives that point back are praise, not denial: "I led X, and I could not be prouder of it", "...never missed one",
# "...never regretted it", and anything in the would-have form: "I couldn't have done it alone".
PRAISE = re.compile(
    r"\b(?:be|prouder|happier|better|more|enough|wait|forg[eo]t\w*|regret\w*|chang\w*|stop\w*|miss\w*|say|imagine|believe|"
    r"recommend|overstate|thank|trade|resist|want|ask|lov\w*|enjoy\w*|tire[ds]?|tiring|have\s+(?:been|done|\w+ed|\w+en))\b",
    re.I,
)
# How far either side of a claim the denial check reads. A denial sits within a few words of what it denies, and reading
# the whole sentence for every claim in it takes time that grows with the square of its length.
DENIAL_WINDOW = 300
# A claim the sentence puts in someone else's mouth isn't yours: "Your posting lists X as a plus, and I have not worked
# under Y".
ATTRIBUTED = re.compile(
    r"\b(?:posting|role|job|position|description|you|your)\b[^.;]{0,60}?"
    r"\b(?:lists?|asks?|requires?|mentions?|wants?|calls?|prefers?|names?|includes?|needs?)\b(?:\W+\w+){0,3}?\W*$",
    re.I,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")


def either_side(sentence: str, match: re.Match[str]) -> tuple[str, str]:
    """The words before and after a claim that could deny it."""
    return sentence[max(0, match.start() - DENIAL_WINDOW):match.start()], sentence[match.end():match.end() + DENIAL_WINDOW]


def disclaimed(before: str, after: str, disclaimers: list[str]) -> bool:
    """Whether a sentence denies the claim it names.

    A negative counts when it leads up to the claim ("I have not led X"), or when the writer denies it in the
    first person afterwards ("the posting lists X, and I have not done it"). A stray negative later
    on denies nothing: "Led X with no delays" is still a claim.
    """
    clause = CLAUSE_BREAK.split(NOT_A_NEGATIVE.sub(" ", before))[-1]
    for pattern in disclaimers:
        for negative in re.finditer(pattern, clause, re.I):
            if len(clause[negative.end():].split()) <= DENIAL_REACH:
                return True
    denials = list(FIRST_PERSON_DENIAL.finditer(after))
    for denial in denials:
        back = REFERS_BACK.match(after, denial.end())
        if back and not PRAISE.search(back.group(0)):
            return True
    # A claim the sentence puts in another's mouth needs only a denial of your own after it, of anything, so long
    # as it is one: "the posting asks for X, and I have never missed an audit leading it" is praise, and claims X.
    plain = [denial for denial in denials if not PRAISE.search(" ".join(after[denial.end():].split()[:4]))]
    return bool(plain) and ATTRIBUTED.search(before) is not None


def unsupported(text: str, patterns: list[str], disclaimers: list[str], label: str) -> tuple[list[str], list[str]]:
    """Errors for unsupported claims, and the exact words of the claims that were properly disclaimed."""
    errors, denied = [], []
    for sentence in SENTENCE.split(text):
        claimed = False
        # Every mention counts, not just the first: "I have not worked under X, but led X audits" claims X.
        for match in (m for pattern in patterns for m in re.finditer(pattern, sentence, re.I)):
            if disclaimed(*either_side(sentence, match), disclaimers):
                denied.append(match.group(0))
            else:
                claimed = True
        if claimed:
            errors.append(f"{label} makes an unsupported claim: {sentence.strip()[:140]!r}")
    return errors, denied


def explain(sentence: str, forbidden: list[str], patterns: list[str], disclaimers: list[str]) -> dict[str, Any]:
    """How the confidential and unsupported checks read one piece of text: the text as the checks see it, and each
    match in it as never (confidential), claim (unsupported and claimed) or denied (unsupported, but the sentence denies
    it). It uses the same patterns and the same reading of a denial as a draft's check, so a sentence that passes here
    passes there."""
    text = matchable(sentence)
    hits: list[dict[str, Any]] = []
    for pattern in forbidden:
        hits += [{"start": m.start(), "end": m.end(), "kind": "never", "pattern": pattern}
                 for m in re.finditer(pattern, text, re.I) if m.end() > m.start()]
    at = 0
    for part in SENTENCE.split(text):
        at = text.index(part, at)
        for pattern in patterns:
            for m in re.finditer(pattern, part, re.I):
                if m.end() == m.start():
                    continue
                denied = disclaimed(*either_side(part, m), disclaimers)
                hits.append({"start": at + m.start(), "end": at + m.end(), "kind": "denied" if denied else "claim",
                             "pattern": pattern})
        at += len(part)
    hits.sort(key=lambda hit: (hit["start"], -hit["end"]))
    return {"text": text, "hits": hits, "blocked": any(hit["kind"] != "denied" for hit in hits)}
