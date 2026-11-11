"""Text as a reader sees it, and the characters that would make a word read one way and match another."""
import re
import unicodedata

# Markdown emphasis can split a word in two that renders whole: **Blue****bird**, or _40_. Underscores inside a word stay.
EMPHASIS = re.compile(r"\*+|(?<!\w)_+|_+(?!\w)")
PLACEHOLDER = re.compile(
    r"\[[^\]]*\]|\{\{|\{[^{}\n]{0,40}\}|\bTODO\b|\bTBD\b|\bFIXME\b|\bX{2,}\b|<[A-Za-z_ ]+>"
)
# A note to yourself in the source, which the builder leaves out of every document. The same as build_resume.COMMENT.
COMMENT = re.compile(r"<!--.*?-->", re.S)
# A blank to fill in, such as ___%. Looked for before emphasis markers are taken out, since those are underscores too.
BLANK = re.compile(r"_{3,}")
# Letters from other alphabets, and Latin small capitals, that a reader takes for plain Latin ones. A word spelled only
# with these and plain letters reads as English and matches nothing: ВӏуеЬird, ʙʟᴜᴇʙɪʀᴅ.
LOOKALIKES = str.maketrans(
    "АВСЕНІЈКМОРЅТХУԚԜҮҺӀ" "асеһіјӏорԛѕԁуҳхԝүɡ" "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ" "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘʀꜱᴛᴜᴠᴡʏᴢ",
    "ABCEHIJKMOPSTXYQWYHI" "acehijlopqsdyxxwyg" "ABEZHIKMNOPTYX" "abcdefghijklmnoprstuvwyz",
)
# Latin letters that don't decompose into a plain one plus an accent. They're real letters in names (Łukasz, Søren,
# Işık), so they're never an error, but a check reads them as the plain letter so they can't split a word.
PLAIN_LATIN = str.maketrans({"ı": "i", "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ħ": "h", "Ħ": "H"})
# A unit written with the micro or ohm sign, such as µm, µs or kΩ. It sets a Greek letter beside Latin ones by design,
# and hides nothing.
UNIT = re.compile(r"[µμ][A-Za-z]{1,3}|[kKMGmµμ]?[ΩΩ]")


def disguises(text: str, label: str) -> list[str]:
    """Characters that make a word read one way and match another: invisible ones, look-alike letters from another
    alphabet, and alphabets mixed inside a word. None belongs in text a person will read and sign."""
    errors = []
    hidden = sorted({f"U+{ord(ch):04X}" for ch in text.lstrip("﻿") if unicodedata.category(ch) == "Cf"})
    if hidden:
        errors.append(f"{label} contains invisible characters ({', '.join(hidden[:5])}). Retype the lines that hold them.")
    lookalike = list(dict.fromkeys(w for w in re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", text)) if is_lookalike(w)))
    mixed = []
    for word in re.findall(r"[^\W\d_]+", text):
        scripts = {unicodedata.name(ch, "?").split(" ")[0] for ch in word}
        if ("LATIN" in scripts and len(scripts) > 1 and word not in mixed and not UNIT.fullmatch(word)
                and not is_lookalike(unicodedata.normalize("NFKC", word))):
            mixed.append(word)
    if lookalike:
        errors.append(f"{label} spells words in look-alike letters from another alphabet, which hides them from the checks "
                      f"and from screening software: {', '.join(lookalike[:5])}. Retype them.")
    if mixed:
        errors.append(f"{label} mixes alphabets inside a word, which hides it from the checks: {', '.join(mixed[:5])}")
    return errors


def is_lookalike(word: str) -> bool:
    """Whether a word is spelled only with plain Latin letters and letters that pass for them, using at least one of
    the latter. A word in another language has letters with no Latin double, so it isn't one."""
    folded = word.translate(LOOKALIKES)
    return folded != word and folded.isascii()


def _fold_lookalikes(match: re.Match[str]) -> str:
    word = match.group(0)
    return word.translate(LOOKALIKES) if is_lookalike(word) else word


def matchable(text: str) -> str:
    """The text as a reader sees it: compatibility forms folded (full-width digits, no-break spaces), accents and
    look-alike letters read as the plain letter, invisible characters, notes and emphasis markers gone. Every check reads
    this, and so do the sources it's compared with, so a word split by formatting or an accent is still that word.

    A note, `<!-- … -->`, prints nothing, so a word or number split by one prints whole: ph<!---->d is phd, and
    4<!---->4 is 44. Its own text prints nowhere either, so it's left out rather than judged."""
    text = unicodedata.normalize("NFKD", COMMENT.sub("", text))
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Mn"))
    text = unicodedata.normalize("NFC", text).translate(PLAIN_LATIN)
    text = re.sub(r"[^\W\d_]+", _fold_lookalikes, text)
    return EMPHASIS.sub("", text)


def set_aside(body: str, phrase: str) -> str:
    """The body with a phrase blanked out where it stands as words, so a company called Meta leaves Metadata alone."""
    phrase = phrase.strip()
    return re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", body) if phrase else body
