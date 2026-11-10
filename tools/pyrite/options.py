"""How Pyrite runs, for the dashboard's Settings tab: which Claude model judges and writes and how hard it thinks,
where replies are read from, how much the morning run does, and what the dashboard reminds you of.

Each setting is one key in search.toml, named in SECTIONS with what it may hold. The page draws its forms from that
list, and a save sets those keys and nothing else, so the rest of the file keeps its layout and comments and no key
outside the list can be reached from the browser. The dashboard has no login, so nothing here may let drafts say more:
[guard], the filters and the allowed hosts aren't in the list, and a save that would loosen a check is refused rather
than sent for a code. What a posting must match to rank higher is a separate matter, handled in settings.py.
"""
import hashlib
import json
import threading
import time
import tomllib
from typing import Any

from . import confirm, deadline, doctor, inbox, mail, outlook, profile, settings, store, tomledit

CLAUDE_DEFAULT = "Claude Code's default"
# Claude Code is asked whether it's signed in at most this often, since asking starts it.
CLAUDE_CHECK_SECONDS = 60

_status_lock = threading.Lock()
_claude_seen: tuple[float, dict[str, Any]] | None = None


def _field(where: str, kind: str, label: str, hint: str = "", **more: Any) -> dict[str, Any]:
    """One setting: `where` is its table and key in search.toml, as "run.tailor_per_day".

    `kind` is "model", "choice", "number" or "switch". `default` is what Pyrite uses while the key isn't in the file,
    and `unset` says that in words. A number with `required` can't be left empty, because Pyrite has no default for it.
    """
    table, key = where.rsplit(".", 1)
    return {"id": where, "table": table, "key": key, "kind": kind, "label": label, "hint": hint, **more}


def _model(where: str, label: str, hint: str, default: str) -> dict[str, Any]:
    return _field(where, "model", label, hint, default=default, unset=default)


SECTIONS: tuple[dict[str, Any], ...] = (
    {"id": "claude", "label": "Claude", "status": "claude",
     "intro": "Pyrite judges and writes through Claude Code on this computer, signed in to your own Claude plan.",
     "panels": (
         {"title": "Model and effort",
          "hint": "For judging postings, tailoring, Refresh resume and Interview prep. A larger model or more effort "
                  "writes better drafts and uses more of your plan.",
          "fields": (
              _field("claude.model", "model", "Model", "A name or alias Claude Code knows, such as opus or sonnet.",
                     unset=CLAUDE_DEFAULT),
              _field("claude.effort", "choice", "Effort", "How hard it thinks before it answers.",
                     choices=[[effort, effort] for effort in store.EFFORTS], unset=CLAUDE_DEFAULT),
          )},
         {"title": "Models for the smaller jobs",
          "hint": "These copy or look things up, so a smaller model does them well for less.",
          "fields": (
              _model("inbox.model", "Reading mail", "Used when replies are read through Gmail.", mail.DEFAULT_MODEL),
              _model("market.model", "Industry outlooks", "Researches an outlook when you ask for one.", outlook.DEFAULT_MODEL),
              _model("skills.model", "Skill ages", "Used when research = true under [skills].", outlook.DEFAULT_MODEL),
          )},
     )},
    {"id": "mail", "label": "Mail", "status": "mail",
     "intro": "Pyrite reads the sender, subject and date of recent mail to spot replies to your applications. "
              "It never sends, moves or deletes anything.",
     "panels": (
         {"title": "Reading replies", "hint": "",
          "fields": (
              _field("inbox.source", "choice", "Read mail through",
                     "IMAP uses no AI and needs an app password in a file on this computer. The Gmail connector needs "
                     "Gmail connected in Claude, keeps no password on disk, warns about job scams, and costs one short "
                     "Claude run each time.",
                     choices=[["imap", "IMAP, with an app password"], ["gmail", "The Gmail connector in Claude Code"]],
                     default="imap"),
              _field("inbox.lookback_days", "number", "Days of mail to read", "Only mail since you applied can match.",
                     default=inbox.DEFAULT_LOOKBACK_DAYS, unset=str(inbox.DEFAULT_LOOKBACK_DAYS), min=1, max=90),
          )},
     ),
     "notes": ("Employers whose mail comes from another domain are listed under [inbox.domains] in profile/search.toml. "
               "docs/mail.md covers setting up either way of reading.",)},
    {"id": "run", "label": "Daily run", "status": None,
     "intro": "What the morning Claude run does. When it runs is up to your computer's scheduler: docs/schedule.md says how.",
     "panels": (
         {"title": "Each morning", "hint": "",
          "fields": (
              _field("run.triage_per_day", "number", "Postings judged", "The most Claude reads and judges in one run.",
                     required=True, min=0, max=200),
              _field("run.tailor_per_day", "number", "Resumes written", "The most it tailors in one run.",
                     required=True, min=0, max=50),
              _field("run.fix_attempts", "number", "Tries at a draft",
                     "Failed fact checks before the run stops retrying a draft, until you ask for it again.",
                     default=store.DEFAULT_FIX_ATTEMPTS, unset=str(store.DEFAULT_FIX_ATTEMPTS), min=1, max=20),
              _field("run.cover_letters", "switch", "Write a cover letter with each resume", default=True),
          )},
     )},
    {"id": "dashboard", "label": "Dashboard", "status": None,
     "intro": "What the to-do list reminds you of, and whether Pyrite looks for a newer copy of itself.",
     "panels": (
         {"title": "Reminders", "hint": "",
          "fields": (
              _field("run.follow_up_days", "number", "Follow up after", "Days after applying.", required=True, min=1, max=90),
              _field("run.quiet_days", "number", "Probably ghosted after", "Days after applying with nothing heard.",
                     required=True, min=1, max=365),
              _field("run.decide_days", "number", "Closing soon within",
                     "Days before a deadline. The job goes on the to-do list, and the run does it first.",
                     default=deadline.DECIDE_DAYS, unset=str(deadline.DECIDE_DAYS), min=1, max=60),
              _field("dashboard.reach_out", "switch", "Remind me to reach out after applying",
                     "One to-do item, a day to three after you apply, to write to the hiring manager.", default=True),
          )},
         {"title": "Updates", "hint": "",
          "fields": (
              _field("dashboard.check_updates", "switch", "Ask GitHub for a newer Pyrite",
                     "Once an hour. Off, GitHub is never asked: update with git pull instead.", default=True),
          )},
     ),
     "notes": ("The port, and the extra names the dashboard answers to, can only be changed under [dashboard] in "
               "profile/search.toml.",)},
)
FIELDS: dict[str, dict[str, Any]] = {field["id"]: field for section in SECTIONS for panel in section["panels"] for field in panel["fields"]}


def _held(cfg: dict[str, Any], field: dict[str, Any]) -> Any:
    """What the file holds for a setting, or None if the key isn't there."""
    table = cfg.get(field["table"])
    return table.get(field["key"]) if isinstance(table, dict) else None


def _in_use(cfg: dict[str, Any], field: dict[str, Any]) -> Any:
    held = _held(cfg, field)
    return field.get("default") if held is None else held


def _version(cfg: dict[str, Any]) -> str:
    held = {name: _held(cfg, field) for name, field in FIELDS.items()}
    return hashlib.sha256(json.dumps(held, sort_keys=True, default=str).encode()).hexdigest()[:16]


def view() -> dict[str, Any]:
    """The sections as the page draws them, each setting with what the file holds now."""
    cfg = tomllib.loads(settings._read())

    def shown(field: dict[str, Any]) -> dict[str, Any]:
        # A switch or a list to pick from always shows a value, so it shows the default while the key is unset.
        value = _held(cfg, field) if field["kind"] in ("model", "number") or "default" not in field else _in_use(cfg, field)
        return {**{k: v for k, v in field.items() if k not in ("table", "key")}, "value": value}

    return {"version": _version(cfg), "editable": not store.IS_EXAMPLE,
            "sections": [{**section, "panels": [{**panel, "fields": [shown(field) for field in panel["fields"]]}
                                                for panel in section["panels"]]} for section in SECTIONS]}


def _clean(field: dict[str, Any], raw: Any) -> Any:
    """What the page sent for one setting, as the value to write, or None to take the key out. Raises ValueError,
    naming the setting, for anything it can't hold."""
    label, kind = field["label"], field["kind"]
    empty = raw is None or raw == ""
    if kind == "switch":
        if not isinstance(raw, bool):
            raise ValueError(f"{label} is either on or off.")
        return raw
    if kind == "number":
        if empty:
            if field.get("required"):
                raise ValueError(f"{label} needs a number.")
            return None
        low, high = field["min"], field["max"]
        if isinstance(raw, bool) or not isinstance(raw, int) or not low <= raw <= high:
            raise ValueError(f"{label} must be a whole number from {low} to {high}.")
        return raw
    if kind == "choice":
        if empty and "default" not in field:
            return None
        if raw not in [value for value, _label in field["choices"]]:
            raise ValueError(f"{label}: that isn't one of the choices.")
        return raw
    if empty:
        return None
    if not isinstance(raw, str) or not store.MODEL_NAME.fullmatch(raw.strip()):
        raise ValueError(f"{label}: that isn't a model's name. Use one such as sonnet or claude-sonnet-5-5.")
    return raw.strip()


def save(body: dict[str, Any]) -> dict[str, Any]:
    """Set the settings named in `values`, each by its id, and leave every other line of search.toml as it was."""
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so settings can't be saved. Point PYRITE_HOME at your own workspace to change them.")
    values = body.get("values")
    if not isinstance(values, dict) or not values:
        raise ValueError("Nothing to save.")
    with settings._lock:
        text = settings._read()
        current = tomllib.loads(text)
        if body.get("version") != _version(current):
            raise settings.Conflict("These settings changed after you opened them, so nothing was saved. Reload Settings to see the latest.")
        updated = text
        for name, raw in values.items():
            field = FIELDS.get(name)
            if field is None:
                raise ValueError(f"{name} isn't a setting this tab can change.")
            value = _clean(field, raw)
            if value is None:
                updated = tomledit.delete_value(updated, field["table"], field["key"])
            elif value != _in_use(current, field):
                updated = tomledit.set_value(updated, field["table"], field["key"], value)
        if updated == text:
            return view()
        # Nothing in SECTIONS loosens the fact check or names a host. This holds that to be true of what's written.
        if confirm.file_only("config", text, updated) or confirm.loosening("config", text, updated):
            raise ValueError("That would loosen a check on what drafts may say, which this tab never does. Nothing was saved.")
        problems = store.config_problems(tomllib.loads(updated))
        if problems:
            raise ValueError(f"{problems[0]} Nothing was saved.")
        profile.keep({"config": text}, "Changed on the Settings tab")
        settings._write(store.CONFIG_PATH, updated)
    return view()


def status(cfg: dict[str, Any], fresh: bool = False) -> dict[str, Any]:
    """Whether Claude Code is signed in and the mail reader is working, for the top of their sections, each as
    {"ok", "what", "fix"}. Claude Code's answer is kept for a minute unless `fresh` asks again."""
    global _claude_seen
    with _status_lock:
        if fresh or _claude_seen is None or time.monotonic() - _claude_seen[0] > CLAUDE_CHECK_SECONDS:
            _claude_seen = (time.monotonic(), doctor.claude_check())
        claude = _claude_seen[1]
    source = str((cfg.get("inbox") or {}).get("source", "imap"))
    return {"claude": claude, "mail": {**doctor.mail_check(cfg), "last_ok": doctor.last_mail_check(source)[0]}}
