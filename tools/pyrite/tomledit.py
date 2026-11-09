"""Changes one setting in a TOML file and leaves every other byte as it was.

search.toml is written by hand, and its comments explain the settings. tomllib reads TOML but can't write it, and
writing the whole file out again would lose every comment. So this finds the exact span of one value, swaps only
that span, then reads the result back to prove that the change asked for is the only thing that changed. Anything it
can't do safely raises EditError and changes nothing.
"""
import copy
import json
import re
import tomllib
from dataclasses import dataclass
from typing import Any

BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
# TOML allows neither of these in a single-line string, and DEL in no basic string at all.
CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
# An array that fits in this many characters stays on one line, unless it was already split over several.
INLINE_WIDTH = 120

Path = tuple[str, ...]


class EditError(ValueError):
    """The change can't be made safely, so nothing was changed."""


@dataclass
class Header:
    """A [table] or [[array of tables]] line."""
    name: Path
    array: bool
    start: int  # Where its line starts.
    end: int  # Just past its line's end.


@dataclass
class Pair:
    """A `key = value` statement, with the span of the value alone."""
    table: Path
    array: bool  # Whether its table is one entry of an array of tables.
    key: Path
    start: int
    value_start: int
    value_end: int
    end: int


def path(table: str | Path) -> Path:
    """A table's path from its dotted name, such as "watch.greenhouse". The root table is "" or ()."""
    if isinstance(table, tuple):
        return table
    if not table:
        return ()
    parts, end = _key(table, 0)
    if end != len(table):
        raise EditError(f"{table!r} isn't a table name.")
    return parts


# ---------- reading ----------

def _ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t":
        i += 1
    return i


def _line_end(text: str, i: int) -> int:
    found = text.find("\n", i)
    return len(text) if found < 0 else found + 1


def _string_end(text: str, i: int) -> int:
    """Just past the string that starts at i."""
    for quote in ('"""', "'''"):
        if text.startswith(quote, i):
            j = i + 3
            while True:
                if quote == '"""' and text.startswith("\\", j):
                    j += 2
                    continue
                if text.startswith(quote, j):
                    j += 3
                    # Up to two more quotes right before the closing three belong to the string.
                    extra = 0
                    while extra < 2 and text.startswith(quote[0], j):
                        j += 1
                        extra += 1
                    return j
                if j >= len(text):
                    raise EditError("A multi-line string never ends.")
                j += 1
    quote = text[i]
    j = i + 1
    while j < len(text):
        char = text[j]
        if quote == '"' and char == "\\":
            j += 2
            continue
        if char == quote:
            return j + 1
        if char == "\n":
            break
        j += 1
    raise EditError("A string never ends on its line.")


def _key(text: str, i: int) -> tuple[Path, int]:
    """A dotted key starting at i, and where it ends."""
    parts = []
    while True:
        i = _ws(text, i)
        if i < len(text) and text[i] in "\"'":
            end = _string_end(text, i)
            parts.append(tomllib.loads(f"k = {text[i:end]}")["k"])
            i = end
        else:
            match = BARE_KEY.match(text, i)
            if not match:
                raise EditError(f"Expected a key at character {i}.")
            parts.append(match.group())
            i = match.end()
        i = _ws(text, i)
        if text.startswith(".", i):
            i += 1
            continue
        return tuple(parts), i


def _value_end(text: str, i: int) -> int:
    """Just past the value that starts at i, which may run over several lines if it's an array or a long string."""
    if i >= len(text):
        raise EditError("A key has no value.")
    if text[i] in "\"'":
        return _string_end(text, i)
    if text[i] in "[{":
        depth = 0
        j = i
        while j < len(text):
            char = text[j]
            if char in "\"'":
                j = _string_end(text, j)
                continue
            if char == "#":
                j = _line_end(text, j)
                continue
            if char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        raise EditError("An array or inline table never closes.")
    j = i
    while j < len(text) and text[j] not in "\r\n#,]}":
        j += 1
    while j > i and text[j - 1] in " \t":
        j -= 1
    if j == i:
        raise EditError("A key has no value.")
    return j


def _rest_of_line(text: str, j: int) -> int:
    """Past the end of the line, allowing only spaces and a comment after a statement."""
    j = _ws(text, j)
    if j >= len(text):
        return j
    if text[j] == "#" or text[j] in "\r\n":
        return _line_end(text, j)
    raise EditError(f"Unexpected text after a statement at character {j}.")


def scan(text: str) -> list[Header | Pair]:
    """Every table header and key in the file, in order, with where each one sits."""
    found: list[Header | Pair] = []
    table: Path = ()
    array = False
    i = 0
    while i < len(text):
        start = i
        i = _ws(text, i)
        if i >= len(text):
            break
        char = text[i]
        if char in "\r\n#":
            i = _line_end(text, i)
            continue
        if char == "[":
            array = text.startswith("[[", i)
            name, j = _key(text, i + (2 if array else 1))
            close = "]]" if array else "]"
            if not text.startswith(close, j):
                raise EditError(f"A table header at character {i} doesn't close.")
            end = _rest_of_line(text, j + len(close))
            table = name
            found.append(Header(name, array, start, end))
            i = end
            continue
        key, j = _key(text, i)
        if not text.startswith("=", j):
            raise EditError(f"Expected '=' after a key at character {j}.")
        value_start = _ws(text, j + 1)
        value_end = _value_end(text, value_start)
        end = _rest_of_line(text, value_end)
        found.append(Pair(table, array, key, start, value_start, value_end, end))
        i = end
    return found


def get_text(text: str, table: str | Path, key: str) -> str | None:
    """The value of a key exactly as the file writes it, or None if it isn't there."""
    table = path(table)
    for item in scan(text):
        if isinstance(item, Pair) and item.table == table and item.key == (key,) and not item.array:
            return text[item.value_start:item.value_end]
    return None


# ---------- writing ----------

def _string(value: str, literal: bool) -> str:
    # A literal string keeps a pattern's backslashes readable, but can't hold a quote mark or a line break.
    if literal and "'" not in value and not CONTROL.search(value):
        return f"'{value}'"
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def key_text(key: str) -> str:
    return key if BARE_KEY.fullmatch(key) else _string(key, literal=False)


def dump(value: Any, literal: bool = False, layout: str | None = None, eol: str = "\n") -> str:
    """A value as TOML. Strings are literal ('...') when `literal` is set and they can be, except inside an inline
    table, where only a string with a backslash is: there it's a pattern, and anything else is a name.

    `layout` is how an array is set out: "inline" on one line, "packed" over lines as full as INLINE_WIDTH allows,
    or "lines" with one item to a line. None picks inline, or lines if it won't fit on one."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:
            return "nan"
        if value in (float("inf"), float("-inf")):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, str):
        return _string(value, literal)
    if isinstance(value, dict):
        if not value:
            return "{}"
        def field(v: Any) -> str:
            pattern = literal and isinstance(v, str) and "\\" in v
            return dump(v, pattern, "inline")
        return "{ " + ", ".join(f"{key_text(k)} = {field(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        items = [dump(item, literal, "inline") for item in value]
        one_line = "[" + ", ".join(items) + "]"
        if layout is None:
            layout = "inline" if len(one_line) <= INLINE_WIDTH else "lines"
        if layout == "inline" or not items:
            return one_line
        if layout == "lines":
            return "[" + eol + "".join(f"  {item},{eol}" for item in items) + "]"
        lines, line = [], "  "
        for item in items:
            if line.strip() and len(line) + len(item) + 2 > INLINE_WIDTH:
                lines.append(line.rstrip())
                line = "  "
            line += f"{item}, "
        lines.append(line.rstrip())
        return "[" + eol + eol.join(lines) + eol + "]"
    raise EditError(f"Can't write a {type(value).__name__} to TOML.")


def _layout(old: str, value: Any) -> str | None:
    """How an existing array is set out, so a change keeps its shape. A one-line array that outgrows its line is
    packed, which keeps it short."""
    if not isinstance(value, list) or not old.startswith("["):
        return None
    if "\n" not in old:
        return "inline" if len(dump(value, layout="inline")) <= INLINE_WIDTH else "packed"
    inner = [line for line in old.splitlines()[1:-1] if line.strip() and not line.strip().startswith("#")]
    try:
        was = tomllib.loads(f"v = {old}")["v"]
    except tomllib.TOMLDecodeError:
        return None
    return "packed" if len(was) > len(inner) else "lines"


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _parse(text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise EditError(f"The file wouldn't read as TOML afterwards ({err}), so nothing was changed.") from err


def _place(config: dict, table: Path) -> dict:
    for part in table:
        config = config.setdefault(part, {})
        if not isinstance(config, dict):
            raise EditError(f"{'.'.join(table)} isn't a table.")
    return config


def _checked(old: str, new: str, table: Path, change) -> str:
    """The new text, once it's proved to read as the old one with only this change made."""
    expected = copy.deepcopy(_parse(old))
    change(_place(expected, table))
    if _parse(new) != expected:
        raise EditError("Making that change would have changed something else in the file, so nothing was changed.")
    return new


def _refuse_arrays(items: list[Header | Pair], table: Path) -> None:
    if any(isinstance(item, Header) and item.name == table and item.array for item in items):
        raise EditError(f"[[{'.'.join(table)}]] is a list of tables. Replace the whole list with replace_table.")


def set_value(text: str, table: str | Path, key: str, value: Any, literal: bool = False) -> str:
    """The text with one key set. An existing value keeps its place, its comment and whether it was split over lines.
    A new key goes after the last key in its table, and a new table at the end of the file."""
    table = path(table)
    items = scan(text)
    _refuse_arrays(items, table)
    eol = _eol(text)
    pairs = [item for item in items if isinstance(item, Pair) and item.table == table and not item.array]
    same = [pair for pair in pairs if pair.key == (key,)]
    if same:
        pair = same[0]
        layout = _layout(text[pair.value_start:pair.value_end], value)
        new = text[:pair.value_start] + dump(value, literal, layout, eol) + text[pair.value_end:]
    else:
        line = f"{key_text(key)} = {dump(value, literal, None, eol)}{eol}"
        headers = [item for item in items if isinstance(item, Header)]
        if pairs:
            at = pairs[-1].end
        elif table == ():
            at = headers[0].start if headers else len(text)
            line += eol if headers else ""
        else:
            header = next((h for h in headers if h.name == table), None)
            if header:
                at = header.end
            else:
                at = len(text)
                line = f"{eol}[{'.'.join(key_text(part) for part in table)}]{eol}{line}"
        prefix = eol if at == len(text) and text and not text.endswith("\n") else ""
        new = text[:at] + prefix + line + text[at:]
    return _checked(text, new, table, lambda place: place.__setitem__(key, value))


def _items(text: str, pair: Pair) -> list[tuple[int, int]]:
    """Where each string in an array of strings sits."""
    spans = []
    j = pair.value_start + 1
    while j < pair.value_end - 1:
        char = text[j]
        if char in "\"'":
            end = _string_end(text, j)
            spans.append((j, end))
            j = end
        elif char == "#":
            j = _line_end(text, j)
        elif char in "[{":
            raise EditError("That list holds more than text, so it can't be changed an item at a time.")
        else:
            j += 1
    return spans


def edit_list(text: str, table: str | Path, key: str, remove=(), add=(), literal: bool = False) -> str:
    """The text with some strings taken out of an array and others added at its end. Every other item, line and
    comment in the array stays as it was, so a list set out by hand keeps its shape. A key that isn't there is set."""
    table = path(table)
    items = scan(text)
    _refuse_arrays(items, table)
    pair = next((item for item in items if isinstance(item, Pair) and item.table == table and item.key == (key,)
                 and not item.array), None)
    if pair is None:
        return set_value(text, table, key, list(dict.fromkeys(add)), literal) if add else text
    current = _place(_parse(text), table).get(key)
    if not isinstance(current, list) or not all(isinstance(value, str) for value in current):
        raise EditError(f"{key} isn't a list of text, so it can't be changed an item at a time.")
    gone = set(remove)
    expected = [value for value in current if value not in gone]
    for value in add:
        if value not in expected:
            expected.append(value)
    if expected == current:
        return text
    eol = _eol(text)
    new = text
    spans = _items(text, pair)
    for (a, b), value in reversed(list(zip(spans, current, strict=True))):
        if value not in gone:
            continue
        end = _ws(new, b)
        line_start = new.rfind("\n", 0, a) + 1
        if new.startswith(",", end):
            comma = end
            end = _ws(new, comma + 1)
            start = a
            if new[end:end + 1] in ("#", "\r", "\n", "") and new[line_start:a].strip():
                # Last on a line that has others: the space before it goes, and any comment after it stays where it was.
                end = comma + 1
                while start > line_start and new[start - 1] in " \t":
                    start -= 1
        else:
            # The last item: the comma before it goes instead.
            start = a
            while start > pair.value_start + 1 and new[start - 1] in " \t":
                start -= 1
            if new[start - 1] == ",":
                start -= 1
        rest = _ws(new, end)
        if not new[line_start:a].strip() and new[rest:rest + 1] in ("#", "\r", "\n"):
            # Alone on its line: the line goes, with the comment after it, which was about this item.
            start, end = line_start, _line_end(new, rest)
        new = new[:start] + new[end:]
    added = [value for value in expected if value not in current]
    if added:
        pair = next(item for item in scan(new) if isinstance(item, Pair) and item.table == table and item.key == (key,)
                    and not item.array)
        spans = _items(new, pair)
        close = pair.value_end - 1
        dumped = [dump(value, literal) for value in added]
        line_start = new.rfind("\n", pair.value_start, close) + 1
        if line_start > pair.value_start and not new[line_start:close].strip():
            # The bracket closes on its own line: each new item gets a line before it, set in like the last one.
            last = spans[-1] if spans else None
            indent = "  "
            if last:
                row = new.rfind("\n", 0, last[0]) + 1
                indent = new[row:last[0]] if not new[row:last[0]].strip() else "  "
            block = "".join(f"{indent}{item},{eol}" for item in dumped)
            new = new[:line_start] + block + new[line_start:]
            if last and not new[_ws(new, last[1]):].startswith(","):
                new = new[:last[1]] + "," + new[last[1]:]
        else:
            before = new[pair.value_start + 1:close].rstrip()
            joiner = "" if not spans else " " if before.endswith(",") else ", "
            new = new[:pair.value_start + 1] + before + joiner + ", ".join(dumped) + new[close:]
    return _checked(text, new, table, lambda place: place.__setitem__(key, expected))


def delete_value(text: str, table: str | Path, key: str) -> str:
    """The text without one key's line. A key that isn't there leaves the text as it was."""
    table = path(table)
    items = scan(text)
    _refuse_arrays(items, table)
    pair = next((item for item in items if isinstance(item, Pair) and item.table == table and item.key == (key,)
                 and not item.array), None)
    if pair is None:
        return text
    new = text[:pair.start] + text[pair.end:]
    return _checked(text, new, table, lambda place: place.pop(key, None))


def replace_table(text: str, table: str | Path, block: str, expected: Any = None) -> str:
    """The text with a table and its subtables, or a whole [[list of tables]], replaced by `block`. Comments just
    above the next table belong to it, so they stay. A table that isn't there is added at the end. `expected`, if
    given, is what the table must read as afterwards."""
    name = path(table)
    if not name:
        raise EditError("The root table can't be replaced as a block.")
    items = scan(text)
    eol = _eol(text)
    block = block.replace("\r\n", "\n").replace("\n", eol)
    if not block.endswith(eol):
        block += eol
    headers = [item for item in items if isinstance(item, Header)]
    inside = [index for index, header in enumerate(headers) if header.name[:len(name)] == name]
    if not inside:
        new = text.rstrip("\r\n") + eol + eol + block if text.strip() else block
    else:
        if inside != list(range(inside[0], inside[-1] + 1)):
            raise EditError(f"[{'.'.join(name)}] is split up by other tables, so it can't be replaced as one block.")
        start = headers[inside[0]].start
        after = inside[-1] + 1
        end = headers[after].start if after < len(headers) else len(text)
        lines = text[start:end].splitlines(keepends=True)
        # Comments and blank lines at the end of the block belong to whatever comes next.
        keep = len(lines)
        while keep > 1 and (not lines[keep - 1].strip() or lines[keep - 1].lstrip().startswith("#")):
            keep -= 1
        end = start + len("".join(lines[:keep]))
        new = text[:start] + block + text[end:]
    old_config, new_config = _parse(text), _parse(new)

    def without(config: dict) -> dict:
        config = copy.deepcopy(config)
        _place(config, name[:-1]).pop(name[-1], None)
        return config

    if without(old_config) != without(new_config):
        raise EditError("Replacing that table would have changed something else in the file, so nothing was changed.")
    if expected is not None:
        got: Any = new_config
        for part in name:
            got = got.get(part) if isinstance(got, dict) else None
        if got != expected:
            raise EditError(f"[{'.'.join(name)}] didn't read back as intended, so nothing was changed.")
    return new
