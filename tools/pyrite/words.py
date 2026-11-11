"""What the commands a person runs say on a terminal: the same results their JSON gives, in a few lines of words.

JSON stays the form for the daily run, scripts and anything else that reads a command's output through a pipe, so
these are only printed to a terminal. There, Python writes through the console itself, so a dash or an accent shows
as it is, even in Windows PowerShell 5.1, which would decode piped output with the console's code page instead.
Text from a job board can carry terminal control codes, so every string that came from outside goes through `plain`.
"""
import re
from typing import Any

# Everything below a space except tab and newline, and DEL with the C1 codes after it. That covers ESC and CSI,
# which start the sequences that move the cursor, clear the screen or retitle the window.
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# How many new postings `discover` names before it points at `pyrite queue`.
NAMED = 10
REJECTED = {"title": "by title", "location": "by location", "score": "below the score floor", "not_open": "not openings",
            "scam": "with a scam's tells", "expired": "past their deadline"}


def plain(text) -> str:
    """Text that's safe to print on a terminal: it can't move the cursor, clear the screen or retitle the window."""
    return CONTROL.sub("", "" if text is None else str(text))


def plural(count: int, word: str) -> str:
    return f"{count:,} {word}{'' if count == 1 else 's'}"


def _sentence(text: str) -> str:
    """A capital first letter and a full stop, leaving the rest as it was: str.capitalize would lowercase a name in it."""
    return f"{text[:1].upper()}{text[1:]}."


def _ago(hours: float) -> str:
    if hours < 1:
        return "under an hour ago"
    if hours < 48:
        return f"{plural(round(hours), 'hour')} ago"
    return f"{plural(round(hours / 24), 'day')} ago"


def discover(stats: dict[str, Any], new_jobs: list[dict[str, Any]]) -> str:
    """A pan in two or three lines, then the best of what it found. `new_jobs` holds each new job's id, company, title and score."""
    read = f"Read {stats['postings']:,} postings from {plural(stats['sources'], 'source')}"
    if stats.get("partial"):
        read += " picked with --only"
    if stats.get("failed"):
        read += f", {stats['failed']:,} of them failing"
    rejected = {reason: count for reason, count in stats.get("rejected", {}).items() if count}
    line = f"{read}. {stats['new']:,} new"
    if rejected:
        reasons = ", ".join(f"{count:,} {REJECTED.get(reason, reason)}" for reason, count in rejected.items())
        line += f", {sum(rejected.values()):,} filtered out ({reasons})"
    lines = [line + "."]
    moved = [f"{plural(stats[key], what)} {verb}" for key, what, verb in (
        ("closed", "posting", "came down"), ("reposted", "posting", "reposted"), ("redated", "posting", "re-dated"),
        ("ghosted", "application", "marked ghosted"), ("expired", "prospect", "passed on after a deadline went by"),
    ) if stats.get(key)]
    if moved:
        lines.append(_sentence(", ".join(moved)))
    best = sorted(new_jobs, key=lambda job: (-(job["score"] or 0), job["id"]))
    lines += [f"New: #{job['id']} {plain(job['company'])}, {plain(job['title'])} (score {job['score']})" for job in best[:NAMED]]
    if len(best) > NAMED:
        lines.append(f"And {len(best) - NAMED:,} more. `pyrite queue` lists what's waiting, best first.")
    return "\n".join(lines)


def rescore(result: dict[str, Any]) -> str:
    """What `rescore` did to the prospects, naming the ones it dropped, since nothing else of them is left."""
    held = result.get("held", 0)
    total = result["kept"] + result["dropped"] + held
    line = (f"Applied your filters again to {plural(total, 'prospect')}. "
            f"Kept {result['kept']:,} with new scores, dropped {result['dropped']:,} that no longer pass")
    if held:
        line += f", and kept {held:,} you've acted on that no longer pass"
    removed = result.get("removed", [])
    lines = [line + "."] + [f"Dropped: {plain(name)}" for name in removed[:NAMED]]
    if len(removed) > NAMED:
        lines.append(f"And {len(removed) - NAMED:,} more.")
    return "\n".join(lines)


def _queue_line(job: dict[str, Any]) -> str:
    where = f", {plain(job['location'])}" if job.get("location") else ""
    said = [f"score {job['score']}"]
    if job.get("age_days") is not None:
        said.append(f"posted {plural(job['age_days'], 'day')} ago")
    if job.get("priority"):
        said.append("your pick")
    if job.get("fit"):
        said.append(f"fit {job['fit']}")
    if job.get("is_new"):
        said.append("new")
    if job.get("ghost_risk"):
        said.append(f"possible ghost: {plain(job['ghost_reason'])}")
    if job.get("unconfirmed"):
        said.append("not rechecked by the latest pan")
    if job.get("scam_signs"):
        said.append(f"scam signs: {plain(', '.join(job['scam_signs']))}")
    return f"  #{job['id']} {plain(job['company'])}, {plain(job['title'])}{where}. {_sentence('; '.join(said))}"


def queue(data: dict[str, Any]) -> str:
    """`pyrite queue` for a person: when the boards were last read, then each list, best first."""
    hours = data["hours_since_sweep"]
    lines = [f"The last full pan finished {_ago(hours)}." if hours is not None
             else "No full pan has finished yet. `pyrite sweep` runs one."]
    failing = data["failing_sources"]
    if failing:
        names = ", ".join(plain(source["company"]) for source in failing)
        lines.append(f"{plural(len(failing), 'source')} failing: {names}. `pyrite sources` tests them.")
    for heading, jobs, none in (("To judge", data["to_triage"], "Nothing to judge."),
                                ("To tailor", data["to_tailor"], "Nothing to tailor.")):
        lines.append(f"{heading}, best first:" if jobs else none)
        lines += [_queue_line(job) for job in jobs]
    if data["stopped_retrying"]:
        ids = ", ".join(f"#{job_id}" for job_id in data["stopped_retrying"])
        lines.append(f"Stopped retrying after failing the fact check too often: {ids}.")
    return "\n".join(lines)


def job(data: dict[str, Any]) -> str:
    """What you and the filters know about a job. What its board supplied is printed after this, fenced off as data."""
    said = [data["status"].replace("_", " "), f"score {data['score']}"]
    if data.get("track"):
        said.append(f"track {plain(data['track'])}")
    if data.get("priority"):
        said.append("your pick")
    at = f" at {plain(data['company'])}" if data.get("company") else ""
    lines = [f"Job {data['id']}{at}: {', '.join(said)}."]
    if data.get("fit"):
        reason = f": {plain(data['fit_reason'])}" if data.get("fit_reason") else "."
        lines.append(f"Fit {data['fit']}{reason}")
    if data.get("app_folder"):
        lines.append(f"Folder: {plain(data['app_folder'])}")
    if data.get("applied_at"):
        lines.append(f"Applied on {data['applied_at'][:10]}.")
    if data.get("next_action"):
        when = f" on {data['next_action_date']}" if data.get("next_action_date") else ""
        lines.append(f"Next: {plain(data['next_action'])}{when}.")
    return "\n".join(lines)


def check(report: dict[str, Any]) -> str:
    """The assay's verdict: whether it passed, each error and warning on a line of its own, and which drafter built the files."""
    errors, warnings = report["errors"], report["warnings"]
    lines = ["The assay passed this draft." if report["ok"] else f"The assay blocked this draft: {plural(len(errors), 'problem')} to fix."]
    lines += [f"  - {plain(error)}" for error in errors]
    if warnings:
        lines.append(f"{plural(len(warnings), 'warning')}, which don't block it:")
        lines += [f"  - {plain(warning)}" for warning in warnings]
    overlap = report.get("overlap") or {}
    if overlap.get("pct") is not None:
        wanted = len(overlap["covered"]) + len(overlap["missing"])
        lines.append(f"The resume uses {len(overlap['covered'])} of the posting's {wanted} skill terms ({overlap['pct']}%).")
    if "sent_drafter" in report:
        versions = sorted(set(report["sent_drafter"].values()))
        lines.append(f"Sent with drafter {' and '.join(versions)}. What was sent is the record, so it isn't rebuilt."
                     if versions else "A copy of what was sent is kept in its sent folder, so it isn't rebuilt.")
    elif report.get("drafter"):
        versions = sorted(set(report["drafter"].values()))
        lines.append(f"Documents built by drafter {' and '.join(versions)}.")
    return "\n".join(lines)


def _totals(label: str, totals: dict[str, Any]) -> str:
    failed = f", {totals['failed']:,} failed" if totals["failed"] else ""
    return (f"  {label}: {plural(totals['runs'], 'run')}{failed}, {totals['minutes']:g} minutes, "
            f"{totals['input_tokens']:,} tokens in and {totals['output_tokens']:,} out, ${totals['cost_usd']:.2f}")


def usage(data: dict[str, Any]) -> str:
    """`pyrite usage` for a person: the Claude runs Pyrite started, this week, all time and by kind."""
    if not data["all"]["runs"]:
        return "Pyrite hasn't started any Claude runs yet."
    lines = ["Claude runs Pyrite started:", _totals("Last 7 days", data["week"]), _totals("All time", data["all"])]
    lines += [_totals(kind["label"], kind) for kind in data["kinds"]]
    return "\n".join(lines)


def sources(report: list[dict[str, Any]]) -> str:
    """One line a source, the failing ones first, then how many answered."""
    lines = []
    for row in sorted(report, key=lambda r: (r["ok"], r["source"])):
        state = f"{row['count']:>5} jobs" if row["ok"] else f"FAILED {plain(row['error'])}"
        lines.append(f"{plain(row['source']):<40} {plain(row['company']):<24} {state}")
    lines.append(f"{sum(r['ok'] for r in report)}/{len(report)} sources responding")
    return "\n".join(lines)
