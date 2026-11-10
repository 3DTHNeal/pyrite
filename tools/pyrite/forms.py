"""Checks on what a dashboard form sends, shared by every page that turns a form into file text."""
import re

BULLET = re.compile(r"^[-*]\s+")


def one_line(value, what: str, bullet: bool = False) -> str:
    """A form's text field as one trimmed line, or "" for none. Refuses anything else, and a line break or control
    character, which would put a second line into the file the text goes to. With `bullet`, a leading "- " or "* "
    typed by habit is dropped, for text that becomes a bullet of its own. `what` names the field in the refusal."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what} should be text.")
    if "\n" in value or "\r" in value or any(ord(c) < 32 and c != "\t" for c in value):
        raise ValueError(f"{what} can't hold a line break or control characters.")
    text = value.strip()
    return BULLET.sub("", text).strip() if bullet else text
