"""The assay's probe: fabricated lines of the kinds it promises to block, and how many of them it stops.

The Evasion tests in test_assay.py show that each way round the check found so far stays shut. They don't say how much
gets through. This does. Each line below is added, one at a time, to the example candidate's passing resume and passing
cover letter, and the assay either blocks the draft or doesn't. docs/technique.md reports the result.

    python tools/tests/test_assay_probe.py                                  the table
    python tools/tests/test_assay_probe.py --chart docs/images/assay-probe.svg   the chart on that page

A class is checked where its name says a claim must be blocked: "both" in a resume and in a letter, "resume" on a resume
alone, since a letter only warns about a term it doesn't know. A "limit" class holds what docs/assay.md says the check
can miss, and "honest" lines are true of the candidate. Beside each line is whether the first run stopped it, before the
misses it found were fixed, so the chart can show both.

The set is hand-built and small. It measures this check on these lines, not fabrication in general.
"""
import functools
import sys
import unittest
from pathlib import Path
from typing import Any

from support import CFG, LETTER, LETTER_ROLE, RESUME, SOURCES

from pyrite import checks

# (class, gate, [(line, whether the first run stopped it)])
PROBES: list[tuple[str, str, list[tuple[str, bool]]]] = [
    ("Invented numbers", "both", [
        ("- Cut build time by 83%.", True),
        ("- Led a team of 137 engineers.", True),
        ("- Shipped firmware to 5,000 robots.", True),
        ("- Cut motion-controller boot time from 42 s to 5 s.", True),
        ("- Managed a $1.2 million budget.", True),
        ("- Ran a pilot of 80 engineers over 6 weeks.", True),
        ("- Held a 99.9% test pass rate.", True),
        ("- Promoted to lead on March 1, 2011.", True),
        ("- Managed a team of forty engineers.", True),
        ("- Cut latency by 0.5 ms.", True),
        ("- Managed a team of \uff14\uff10 engineers.", True),
        ("- Managed a team of _40_ engineers.", True),
    ]),
    ("Outside links", "both", [
        ("- Demo reel at bit.ly/alexdemo.", True),
        ("- Portfolio at alexrivera.pro", True),
        ("- Write to alex@rivera.studio.", True),
        ("- See https://evil.example for details.", True),
        ("- Profile at linkedin.com/in/someone-else.", True),
        ("- See [my portfolio](portfolio) for details.", True),
    ]),
    ("Invented skills and credentials", "resume", [
        ("- Ran services on AWS and Kubernetes.", True),
        ("- FreeBSD kernel work for the fleet.", True),
        ("- Deep experience with Terraform.", True),
        ("- Certified Kubernetes Administrator.", True),
        ("- M.S., Computer Engineering, University of Wisconsin\u2013Madison, 2012", True),
        ("- B.S., Computer Engineering, Stanford University, 2012", True),
        ("Head of firmware for the whole company.", True),
    ]),
    ("Confidential names, disguised", "both", [
        ("- Delivered the Bluebird controller ahead of schedule.", True),
        ("- Delivered the bluebird controller ahead of schedule.", True),
        ("- Delivered the Blue bird controller ahead of schedule.", True),
        ("- Delivered the Blue-bird controller ahead of schedule.", True),
        ("- Delivered the Blue\u200bbird controller ahead of schedule.", True),
        ("- Delivered the **Blue****bird** controller ahead of schedule.", True),
        ("- Delivered the \u0412luebird controller ahead of schedule.", True),
        ("- Delivered the Blu\u00e9bird controller ahead of schedule.", True),
        ("- Delivered the SkyLift 900 controller ahead of schedule.", True),
        ("- Built tooling for the Hive.", True),
        ("- Delivered the Blue\u2011bird controller ahead of schedule.", False),
        ("- Delivered the Blue\u2013bird controller ahead of schedule.", False),
        ("- Delivered the Blue_bird controller ahead of schedule.", False),
        ("- Delivered the Blue.bird controller ahead of schedule.", True),
        ("- Delivered the Blue/bird controller ahead of schedule.", False),
        ("- Delivered the Blue  bird controller ahead of schedule.", False),
        ("- Delivered the Blue - bird controller ahead of schedule.", False),
        ("- Delivered the B.L.U.E.B.I.R.D. controller ahead of schedule.", False),
        ("- Delivered the Sky\u2011Lift controller ahead of schedule.", False),
        ("- Delivered the Blueb1rd controller ahead of schedule.", False),
    ]),
    ("Unsupported claims", "both", [
        ("- Led ISO 26262 certification for the fleet.", True),
        ("- Led ISO 26262 safety certification with no delays.", True),
        ("- Never failed an ISO 26262 audit.", True),
        ("- Not only led ISO 26262 certification, also audited it.", True),
        ("- With no outside consultants, led ISO 26262 certification.", True),
        ("- Led ISO 26262 certification, and I could not be prouder of it.", True),
        ("- Validated by replaying field failures from robots.", True),
        ("- No stranger to ISO 26262.", False),
        ("- Not new to ISO 26262 audits.", False),
        ("- I have no shortage of ISO 26262 experience.", False),
        ("- No one on the team knew ISO 26262 better.", True),
        ("- Never far from ISO 26262 work.", False),
        ("- Nothing less than full ISO 26262 compliance on every launch.", True),
        ("- Without question the team's ISO 26262 lead.", False),
        ("- I haven't met an ISO 26262 audit I couldn't pass.", True),
        ("- The posting asks for ISO 26262 certification, and I have never missed an audit leading it.", False),
        ("- Not a day went by without ISO 26262 work.", False),
    ]),
    ("A real number at another scale", "both", [
        ("- Saved $3M across the robot launches.", True),
        ("- Saved $3 million across the robot launches.", True),
        ("- Ran 212K automated tests on every merge.", True),
        ("- Ran 212k automated tests on every merge.", True),
        ("- Ran 212 thousand automated tests on every merge.", True),
        ("- Wrote firmware for a fleet of 1.4M robots.", True),
        ("- Saved $3m across the robot launches.", False),
        ("- Saved $3 Million across the robot launches.", True),
        ("- Ran 212 K automated tests on every merge.", False),
        ("- Saved $3 MM across the robot launches.", False),
        ("- Saved $3 mil across the robot launches.", False),
        ("- Processed 3 bn sensor readings.", False),
    ]),
    ("Multiples and fractions", "both", [
        ("- Doubled throughput on the test rig.", True),
        ("- Cut review time tenfold.", True),
        ("- Improved bench throughput 8x.", True),
        ("- Improved settling time by an order of magnitude.", True),
        ("- Bench throughput up 300%.", True),
        ("- Quadrupled test coverage on the bench.", True),
        ("- Doubling test throughput on the rig.", False),
        ("- Made the bench twice as fast.", False),
        ("- Cut review time in half.", False),
        ("- Cut boot time by half.", False),
        ("- Delivered a 3-fold gain in bench throughput.", False),
        ("- Made merges 3 times faster.", False),
        ("- Tripling bench capacity in a quarter.", False),
        ("- Cut settling time by a third.", False),
        ("- Cut escaped defects by two-thirds.", False),
    ]),
    ("Titles built from real words", "resume", [
        ("= Senior Principal Firmware Engineer | Motor Control", False),
        ("- Promoted to Senior Principal Firmware Engineer.", False),
        ("- Certified Firmware Engineer.", False),
        ("- Senior Firmware Engineering Manager for the robot fleet.", False),
        ("**Senior Principal Firmware Engineer** | Madison, WI | Present", True),
    ]),
    ("Real number, wrong claim", "limit", [
        ("- Managed a team of 212 engineers.", False),
        ("- Hired 7 engineers, and 4 were promoted.", False),
        ("- Software lead on 8 robot launches.", False),
        ("- Cut motion-controller boot time from 42 ms to 9 ms.", False),
        ("- Delivered 1,400 tasks with the coding-agent workflow.", False),
        ("- Median review time fell about 35%.", False),
    ]),
    ("Small numbers in words", "limit", [
        ("- Cut review time by nine percent.", False),
        ("- Managed a team of ten engineers.", False),
        ("- Software lead on five robot launches.", False),
    ]),
    ("Lowercase or sentence-opening skills", "limit", [
        ("- Ran services on kubernetes and terraform.", False),
        ("- Wrote the fleet planner in rust.", False),
        ("- Kubernetes cluster administration for the fleet.", False),
    ]),
    ("Plain-prose inventions", "limit", [
        ("- Led the company's migration to a microservices architecture.", False),
        ("- Won the company's top engineering award.", False),
        ("- Owned the firmware budget and every vendor contract.", False),
        ("- Presented motor-control research at international conferences.", False),
    ]),
    ("Honest restatements", "honest", [
        ("- Cut motion-controller boot time from 42 s to 9 s.", False),
        ("- Managed 7 firmware and test engineers.", False),
        ("- Ran 212 automated tests on every merge.", False),
        ("- Settling time down about 35 percent on the test rig.", False),
        ("- Wrote firmware for a fleet of 1.4K warehouse robots.", True),
        ("- Software lead on three robot launches.", False),
        ("- I have not worked under ISO 26262.", False),
        ("- Hired 4 engineers; 2 were promoted.", False),
        ("- Wrote firmware in C++ on FreeRTOS over CAN.", False),
        ("- The posting asks for safety certification, and I have not done it.", False),
    ]),
    ("True but derived", "honest", [
        ("- 14 years of firmware and embedded software experience.", True),
        ("- Cut boot time by 33 seconds.", True),
        ("- Cut boot time 79%.", True),
        ("- Built the HIL bench that gates every merge.", True),
    ]),
]
# How many of each class the assay stops today. A number that moves, either way, is news: correct it here, redraw the
# chart and correct docs/technique.md, which quotes these.
STOPPED = {
    "Invented numbers": 12,
    "Outside links": 6,
    "Invented skills and credentials": 7,
    "Confidential names, disguised": 19,
    "Unsupported claims": 17,
    "A real number at another scale": 11,
    "Multiples and fractions": 15,
    "Titles built from real words": 1,
    "Real number, wrong claim": 0,
    "Small numbers in words": 0,
    "Lowercase or sentence-opening skills": 0,
    "Plain-prose inventions": 0,
    "Honest restatements": 0,
    "True but derived": 4,
}


def stops(line: str, gate: str) -> bool:
    """Whether the assay blocks a draft with this line added, wherever its class says it must."""
    resume, _ = checks.check_text(RESUME + f"\n{line}\n", "resume", CFG, SOURCES, "Acme", "Principal Engineer")
    sentence = line.removeprefix("- ")
    letter, _ = checks.check_text(LETTER.rstrip() + f"\n\n{sentence}\n", "letter", CFG, SOURCES, *LETTER_ROLE)
    if gate == "both":
        return bool(resume) and bool(letter)
    return bool(resume) if gate == "resume" else bool(resume) or bool(letter)


@functools.cache
def results() -> list[dict[str, Any]]:
    """Each class with its lines, as (line, stopped on the first run, stopped now). Worked out once: it's 248 checks."""
    return [{"name": name, "gate": gate, "lines": [(line, first, stops(line, gate)) for line, first in lines]}
            for name, gate, lines in PROBES]


class Probe(unittest.TestCase):
    def test_the_assay_stops_as_many_of_each_class_as_recorded(self):
        for group in results():
            with self.subTest(group["name"]):
                now = sum(stopped for _line, _first, stopped in group["lines"])
                through = [line for line, _first, stopped in group["lines"] if not stopped]
                self.assertEqual(now, STOPPED[group["name"]],
                                 f"the assay stops {now} of {len(group['lines'])}; these get through: {through}")

    def test_nothing_the_first_run_stopped_gets_through_now(self):
        for group in results():
            if group["gate"] != "honest":
                lost = [line for line, first, stopped in group["lines"] if first and not stopped]
                self.assertEqual(lost, [], group["name"])

    def test_honest_restatements_of_the_fact_bank_pass(self):
        honest = next(group for group in results() if group["name"] == "Honest restatements")
        self.assertEqual([line for line, _first, stopped in honest["lines"] if stopped], [])


def table(groups: list[dict[str, Any]]) -> str:
    rows = [f"{'class':40} {'gate':7} {'first run':>9} {'now':>4} {'of':>4}"]
    for group in groups:
        first = sum(first for _line, first, _stopped in group["lines"])
        now = sum(stopped for _line, _first, stopped in group["lines"])
        rows.append(f"{group['name']:40} {group['gate']:7} {first:>9} {now:>4} {len(group['lines']):>4}")
    promised = [entry for group in groups if group["gate"] in ("both", "resume") for entry in group["lines"]]
    rows.append(f"\nPromised classes: {sum(first for _l, first, _s in promised)} stopped on the first run, "
                f"{sum(stopped for _l, _f, stopped in promised)} now, of {len(promised)}.")
    return "\n".join(rows)


def chart(groups: list[dict[str, Any]]) -> str:
    """The promised classes as an SVG, one square to a line: stopped on the first run, stopped now, or still through."""
    ink, soft, brass, good, bad = "#f3eee3", "#a39a89", "#d2b04e", "#6fc790", "#f28b7b"
    sans = "Segoe UI, system-ui, -apple-system, sans-serif"
    promised = [group for group in groups if group["gate"] in ("both", "resume")]
    width, height = 920, 84 + 62 * len(promised)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" font-family="{sans}">',
           "<title>How many fabricated lines the assay stops, by class, on the first run and now</title>",
           f'<rect width="{width}" height="{height}" rx="14" fill="#110f0b"/>']

    def square(x: float, y: float, state: str) -> str:
        if state == "open":
            return f'<rect x="{x + 1.5}" y="{y + 1.5}" width="17" height="17" rx="4" fill="none" stroke="{bad}" stroke-width="3"/>'
        return f'<rect x="{x}" y="{y}" width="20" height="20" rx="4" fill="{brass if state == "held" else good}"/>'

    x = 28.0
    for state, label in (("held", "stopped on the first run"), ("fixed", "stopped now"), ("open", "still gets through")):
        out.append(square(x, 24, state))
        out.append(f'<text x="{x + 30}" y="40" font-size="15" fill="{soft}">{label}</text>')
        x += 46 + 7.6 * len(label)
    for index, group in enumerate(promised):
        top = 84 + 62 * index
        first = sum(first for _line, first, _stopped in group["lines"])
        now = sum(stopped for _line, _first, stopped in group["lines"])
        where = "resume and letter" if group["gate"] == "both" else "resume"
        count = f"{now}" if first == now else f"{first} → {now}"
        out.append(f'<text x="28" y="{top}" font-size="16" font-weight="600" fill="{ink}">{group["name"]}'
                   f'<tspan dx="10" font-size="12" font-weight="400" fill="{soft}">{where}</tspan></text>')
        out.append(f'<text x="{width - 28}" y="{top}" font-size="15" font-weight="600" text-anchor="end" fill="{ink}">{count}'
                   f'<tspan font-weight="400" fill="{soft}"> of {len(group["lines"])}</tspan></text>')
        states = [("held" if first else "fixed" if stopped else "open") for _line, first, stopped in group["lines"]]
        for place, state in enumerate(sorted(states, key=["held", "fixed", "open"].index)):
            out.append(square(28 + 25 * place, top + 12, state))
    return "\n".join([*out, "</svg>"]) + "\n"


if __name__ == "__main__":
    if "--chart" in sys.argv:
        target = Path(sys.argv[sys.argv.index("--chart") + 1])
        target.write_text(chart(results()), encoding="utf-8")
        print(f"Wrote {target}")
    else:
        print(table(results()))
