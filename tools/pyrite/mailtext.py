"""The text of an email: made safe to show, and read for what kind of answer it is.

Whoever sent a message wrote every word of it, so its text is handled as hostile. It's made plain text before anything
keeps it: HTML is reduced to the words a reader would see, with hidden text dropped, and invisible and control
characters go. What the dashboard shows goes further. Each link becomes the name of the site it points to, which can't
be clicked; the quoted history under a reply and the unsubscribe footer are cut; and it's held to a short excerpt.
The page draws it as text only, and it's never handed to Claude.

Kind is read by plain rules, not by a model: a rejection, a receipt that an application arrived, or a response from
someone. It's a guess to read beside the text, and it never changes a job by itself.
"""
import re
from urllib.parse import urlparse

from .sources import html_to_text, strip_invisible

# How much of a message's text is read for the rules, and how much of that is kept to show.
MAX_BODY = 4000
MAX_EXCERPT = 1500
# Shown text is cleared this long after it was read. The mailbox keeps the original.
KEEP_DAYS = 30

REJECTION, RECEIPT, RESPONSE = "rejection", "receipt", "response"
KINDS = (REJECTION, RECEIPT, RESPONSE)

LOOKS_LIKE_HTML = re.compile(r"<\s*(?:html|head|body|div|p|br|table|td|span|a|font|center|style)\b[^>]*>", re.I)
# Control characters other than a tab or a line break. A carriage return is made a line break first.
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Where a reply's quoted history begins: "On Tue, Sam wrote:", an Outlook header block, or a forwarded message.
QUOTED_HISTORY = re.compile(
    r"^(?:On\b[^\n]{0,200}(?:\n[^\n]{0,200})?\bwrote:[ \t]*$"
    r"|-{2,}[ \t]*(?:Original Message|Forwarded message)[ \t]*-{2,}"
    r"|From:[^\n]*\n(?:Sent|Date):)",
    re.I | re.M,
)
QUOTED_LINE = re.compile(r"^[ \t]*>.*$\n?", re.M)
# A web address written out, with the angle brackets plain-text mail puts round one. The address itself never reaches
# the page: only the site's name does.
LINK = re.compile(r"<?\b(?:https?://|www\.)[^\s<>\"'\])]*>?", re.I)
MAIL_LINK = re.compile(r"\bmailto:", re.I)
FOOTER_LINE = re.compile(
    r"^.*\b(?:unsubscribe|opt[- ]out|email preferences|manage (?:your )?(?:notifications?|subscriptions?|email|preferences)"
    r"|view (?:this (?:email|message) )?(?:in|on) (?:your |a )?(?:web )?browser)\b.*$\n?",
    re.I | re.M,
)

# A sentence that says what may happen later, as receipts do: "if you're selected for an interview, we'll be in
# touch". Rejection and response words in it don't count.
CONDITIONAL = re.compile(r"\b(?:if|unless|whether|should (?:you|your|we|there)|once (?:we|our|the)|in the event)\b", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
REJECTION_TEXT = re.compile(
    r"\b(?:unfortunately|regret (?:to|that)|not (?:to )?(?:be )?(?:move|moving|proceed|proceeding|advance|advancing) forward"
    r"|(?:pursue|pursuing|move forward with|moving forward with|proceed with|proceeding with|selected|chosen|go with|going with)"
    r" (?:other|another|a different|more qualified) (?:candidates?|applicants?|individuals?)"
    r"|other (?:candidates|applicants) (?:whose|who)|(?:decided|chosen|elected|opted) not to"
    r"|(?:position|role|requisition|opening) (?:has|have) (?:now )?been (?:filled|closed|cancell?ed)"
    r"|no longer (?:being )?(?:considered|under consideration|in consideration|moving forward)"
    r"|(?:have|has) not been selected|were not selected|not been successful|(?:was|were) unsuccessful"
    r"|will not be (?:moving|proceeding|advancing|offering|extending|able to offer)|not (?:a|the right) (?:fit|match) for)\b",
    re.I,
)
RESPONSE_TEXT = re.compile(
    r"\b(?:interview\w*|schedul\w+|availability|are you (?:free|available)|available (?:for|to) (?:a|an|chat|talk|speak|meet|connect)"
    r"|(?:phone|video|recruiter|initial|intro\w*|screening) (?:screen|call|chat|conversation|meeting)"
    r"|(?:speak|talk|chat|meet|connect) with you|set up (?:a |some )?(?:time|call|meeting|chat)|calendly|book (?:a |some )?time"
    r"|time to (?:chat|talk|connect|speak|meet)|offer (?:letter|of employment)|(?:pleased|happy|excited|delighted) to (?:offer|extend|invite)"
    r"|next (?:round|stage|steps?)|to offer you|(?:take-?home|technical|coding|skills?) (?:assessment|exercise|challenge|test)"
    r"|(?:move|moving|advance|advancing) (?:you|your (?:application|candidacy)) (?:forward|to)|a few questions for you)\b",
    re.I,
)
# Automatic mail that every application sets off, which isn't anyone answering.
RECEIPT_SUBJECT = re.compile(
    r"\b(?:successfully (?:applied|submitted)|thanks? (?:you )?for applying|thanks? (?:you )?for (?:submitting )?your application"
    r"|application (?:was )?(?:received|submitted|complete|confirmation)|received your application|got your application"
    r"|reset (?:your )?password|password reset|verify your (?:email|account)|verification code|one[- ]time (?:pass)?code"
    r"|(?:sign[- ]in|security|access) code)\b",
    re.I,
)
# "Thank you for your interest" is a receipt as often as a rejection. It counts as a receipt only when the message's
# own text is at hand and says neither, since header-only mail can't tell the two apart.
INTEREST_SUBJECT = re.compile(r"\bthanks? (?:you )?for your interest\b", re.I)
RECEIPT_TEXT = re.compile(
    r"\b(?:(?:have |has )?received your (?:application|resume|submission)|thanks? (?:you )?for (?:applying|your application|submitting)"
    r"|application (?:has been |was |is )?(?:received|submitted|complete)|(?:will|we'll|to) (?:carefully |now )?review your"
    r" (?:application|resume|qualifications|background|experience|submission)|(?:is|are) (?:currently )?(?:being )?reviewed"
    r"|(?:is|are) under review|(?:track|check|view) (?:the status of )?your application|candidate (?:home|portal|profile|account)"
    r"|due to the (?:high |large )?volume)\b",
    re.I,
)


def _lines(text: str) -> str:
    """Line breaks kept, at most one blank line in a row, and runs of spaces made one."""
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def body_text(raw: str, html: bool | None = None, limit: int = MAX_BODY) -> str:
    """A message's text as plain text, from its start to where any quoted history begins. `html` says whether it's
    HTML, and None has it judged from the text, since a copy made through Gmail doesn't say."""
    text = str(raw or "")
    if html or (html is None and LOOKS_LIKE_HTML.search(text)):
        text = html_to_text(text)
    text = strip_invisible(text.replace("\r\n", "\n").replace("\r", "\n"))
    text = CONTROL.sub("", text)
    cut = QUOTED_HISTORY.search(text)
    if cut:
        text = text[:cut.start()]
    text = QUOTED_LINE.sub("", text)
    return _lines(text)[:limit]


def _site(link: str) -> str:
    text = link.strip("<>")
    host = urlparse(text if "://" in text else f"//{text}").hostname or ""
    return host.removeprefix("www.") if re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host) else ""


def excerpt(raw: str, limit: int = MAX_EXCERPT) -> str:
    """The start of a message's text as the dashboard shows it: plain text, each link replaced by the name of its site,
    and no quoted history or unsubscribe footer."""
    text = body_text(raw)
    text = LINK.sub(lambda found: f"[link to {site}]" if (site := _site(found.group(0))) else "[link]", text)
    text = MAIL_LINK.sub("", text)
    text = _lines(FOOTER_LINE.sub("", text))
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(None, 1)[0].rstrip(",;:") + " …"


def _plain_sentences(text: str) -> str:
    """The sentences that don't hang on an "if", so a receipt's "if you're selected for an interview" isn't one."""
    return " ".join(part for part in SENTENCE_END.split(text) if part and not CONDITIONAL.search(part))


def reply_kind(subject: str, text: str) -> str:
    """What a reply to an application most likely is: a rejection, a receipt, or a response from someone. "" when
    there's too little to tell, as with a vague subject and no text.

    A rejection's words win over everything, since a rejection often thanks you for applying. A response's words win
    over a receipt's, so mail that's both is shown rather than left out. Either one in a sentence that only says what
    may happen later doesn't count."""
    said = _plain_sentences(f"{subject}\n{text}")
    if REJECTION_TEXT.search(said):
        return REJECTION
    if RESPONSE_TEXT.search(said):
        return RESPONSE
    if RECEIPT_SUBJECT.search(subject) or RECEIPT_TEXT.search(text) or (text.strip() and INTEREST_SUBJECT.search(subject)):
        return RECEIPT
    return RESPONSE if text.strip() else ""
