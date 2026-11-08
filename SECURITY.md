# Security

Pyrite runs on your own machine and holds a job search: resumes, a fact bank, recruiter mail and the answers it types into application forms. A flaw here can expose that, so I'd rather hear about one privately.

## Reporting a problem

Use [GitHub's private advisory form](https://github.com/3DTHNeal/pyrite/security/advisories/new), not a public issue. Say what you ran, what happened and what an attacker gains. Leave your own data out: the fictional workspace in `example/` (`pyrite demo`) can show almost anything.

I'll reply within a week. This is a personal project, so there's no bounty, but I'll credit you in the fix unless you'd rather I didn't.

Only the latest `main` is supported.

## What counts

- The dashboard letting a web page, or another user on the machine, read data or trigger an action. It's meant to answer only `127.0.0.1` and same-origin JSON requests.
- Text in a posting or an email getting a Claude run to step outside its limits, such as editing a file it wasn't given or reading one it's barred from.
- Autofill typing into a page or field other than the one it was pointed at.
- A way past `tools/check_public.py` for the kinds of data it says it catches.

## What doesn't

- Anything that needs your user account on the machine already. Whoever has it can read the workspace directly.
- The misses listed under Limits in the [README](README.md). They're known, not vulnerabilities.
- A flaw in a dependency with no path through Pyrite. Report that upstream.
