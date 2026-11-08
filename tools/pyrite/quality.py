"""Signs a posting isn't a real opening: a talent pool, a listing kept up all year, or a scam's tells.

The boards Pyrite reads belong to the employers, so most of what they list is real. What isn't
says so in its own words: "a general application", "we don't have an open position at the
moment", "an evergreen role we keep open on an ongoing basis". Each pattern here was checked
against thousands of real postings, so ordinary phrases that share a word ("evergreen content",
"building a talent pipeline", "applications are reviewed on a rolling basis") don't count.

Scam postings rarely reach a company's own board, but a posting added by hand can come from
anywhere. Only the tells of a scam on the posting itself count: asking you to pay, to talk over
a chat app, or to deposit a check they send you. A posting that says it would never do these
things is warning you about scams, not running one.
"""
import re
from functools import lru_cache

# A title that names no job at all.
NO_OPENING_TITLE = re.compile(
    r"\b(general application|open application|speculative application|general interest|expression of interest"
    r"|talent (?:pool|community|network)|future (?:opportunities|openings|roles|positions|consideration))\b"
    r"|\bdon['’]?t see (?:a|the|your) (?:right )?(?:role|job|position|fit)\b",
    re.I,
)
# A posting that says there's no opening behind it. "If we don't currently have an open role" is a hedge, not that.
NO_OPENING_TEXT = re.compile(
    r"(?<!\bif )(?<!\bif we )\b(?:we )?(?:don['’]?t|do not|doesn['’]?t|does not) (?:currently )?have (?:an? |any )?(?:open|current|active|immediate) "
    r"(?:position|role|opening|vacanc\w*|requisition)s?\b"
    r"|\bno (?:current|immediate|active) (?:openings?|vacanc\w*)\b"
    r"|\b(?:this|the) (?:posting|position|role|requisition|listing) (?:is )?(?:not (?:for|tied to|attached to|linked to|associated with) "
    r"an? (?:specific|current|open|active|particular) (?:opening|role|position|vacancy|job)"
    r"|(?:is )?for (?:future|potential|upcoming) (?:openings|opportunities|roles|positions|needs|consideration))\b"
    r"|\bsubmit a general application\b",
    re.I,
)
# A listing kept up whether or not anyone is being hired for it right now.
EVERGREEN_TEXT = re.compile(
    r"\b(?:an?|this) [\"“'‘]?evergreen[\"”'’]? (?:role|position|posting|requisition|req|opening|job|listing)\b"
    r"|\b(?:keep|kept|remains?|stays?) (?:\w+ ){0,2}open (?:on an ongoing basis|year[- ]round|continuously|indefinitely|at all times)\b"
    r"|\b(?:accept|review|collect)\w* (?:applications|resumes|candidates) (?:for this (?:role|position) )?"
    r"(?:on an ongoing basis|year[- ]round|continuously)\b"
    r"|\bthis is a pipeline (?:role|requisition|req|posting)\b",
    re.I,
)
SCAM_TEXT = (
    ("Asks you to pay a fee", re.compile(
        r"\b(?:you (?:will |must |are required to |need to |have to )?pay|pay (?:a|an|the)) (?:\S+ ){0,3}(?:application|training"
        r"|processing|registration|background[- ]check|starter[- ]kit) fees?\b"
        r"|\b(?:application|training|processing|registration|starter[- ]kit) fees? (?:of \S+ )?(?:is |are )?(?:required|payable|due)\b",
        re.I)),
    # "Reach customers over WhatsApp" is marketing work. Only you being reached, or interviewed, that way counts.
    ("Wants you to talk over a chat app", re.compile(
        r"\b(?:contact|message|text|reach|add)\w* (?:us|me|our (?:\w+ ){0,2}(?:recruiter|team|manager|hr)) (?:\S+ ){0,3}"
        r"(?:on|via|through|over|using) (?:whats ?app|telegram|signal|wechat)\b"
        r"|\binterview\w* (?:will be |is |are )?(?:held |conducted |done )?(?:on|via|through|over|using) (?:whats ?app|telegram|signal|wechat)\b",
        re.I)),
    # Only a check sent to you counts. Depositing checks is ordinary work in accounts payable, and a home office stipend is a benefit.
    ("Sends you a check to deposit", re.compile(
        r"\b(?:we(?:['’]ll| will)? (?:send|mail|issue|overnight) you a (?:check|cheque)"
        r"|you(?:['’]ll| will) (?:receive|get) a (?:check|cheque) (?:to|for|that you)\b)",
        re.I)),
)
# Postings warn about scams in the same words: "we will never charge an application fee". Those aren't tells.
DENIAL = re.compile(r"\b(?:never|not|no|without|nor)\b|n['’]t\b", re.I)


def _says(pattern: re.Pattern, text: str) -> bool:
    """Whether the text says it, rather than saying it never would."""
    for match in pattern.finditer(text):
        sentence = re.split(r"[.!?\n]", text[max(0, match.start() - 60):match.start()])[-1]
        if not DENIAL.search(sentence):
            return True
    return False


@lru_cache(maxsize=20000)
def not_an_opening(title: str, description: str) -> str:
    """Why the posting is no opening, in plain words, or nothing. Cached: the dashboard asks on every refresh."""
    if NO_OPENING_TITLE.search(title or ""):
        return "the title names no particular job"
    if NO_OPENING_TEXT.search(description or ""):
        return "the posting says there's no opening behind it"
    return ""


@lru_cache(maxsize=20000)
def evergreen(description: str) -> str:
    """Why the posting looks kept up all year, or nothing."""
    return "the posting says it stays up for ongoing hiring, not one opening" if EVERGREEN_TEXT.search(description or "") else ""


@lru_cache(maxsize=20000)
def scam_signs(description: str) -> tuple[str, ...]:
    """The scam tells in a posting's text. Empty means none."""
    return tuple(label for label, pattern in SCAM_TEXT if _says(pattern, description or ""))


def rejection(title: str, description: str) -> str:
    """Why the sweep should drop a posting that passed the filters: "not_open", "scam", or nothing."""
    if not_an_opening(title, description):
        return "not_open"
    return "scam" if scam_signs(description) else ""
