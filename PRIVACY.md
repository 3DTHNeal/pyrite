# Privacy

Pyrite has no server, account or telemetry. It sends nothing to its author. Everything it keeps stays in your workspace on your own computer. Some features do send data to outside services, and this page lists each one so you can decide which to turn on.

## What stays on your computer

Your workspace (the folder `PYRITE_HOME` points to) holds:

- your profile: the fact bank, approved terms, run notes, search settings and Workday answer sheet;
- each application's posting, drafts, notes, built documents and autofill log;
- `data/pyrite.db`: jobs, statuses, timelines, the run log, the time, tokens and estimated cost of each Claude run, and, for possible replies and scam warnings, the sender, subject and date of matching mail.
- `data/history/`: the earlier text of each profile file you change on the dashboard, so any save can be put back;
- `data/market/`: the official employment numbers downloaded for the Industries tab, and the research each industry's outlook found;
- `data/culture/`: what the research on each employer you asked about found.

Your browser also keeps a copy of what the dashboard last showed, in its storage for the dashboard's address, so the next load can show it at once while Pyrite works out the latest. Clearing that site's data in the browser removes it.

The dashboard listens on localhost only. Nothing on it is reachable from another machine unless you set that up yourself.

## What goes where

| Feature | Sent to | What's sent |
|---|---|---|
| Morning pan | Each job board you list | Ordinary requests for public job feeds. The board sees your IP address and Pyrite's user agent. Nothing about you is sent. |
| Triage, drafting, Refresh resume, interview prep | Anthropic, through Claude Code | The posting, and for drafting, refreshes and prep, your fact bank, run notes, approved terms, model documents and existing drafts. Anthropic's terms and privacy policy apply, under your own account. |
| Gmail connector | Google and Anthropic, through Claude Code | Claude reads recent mail through your connected Gmail account and returns the sender, subject, date and a short snippet of each. It's told the names of the companies you've applied to or listed under `[inbox.domains]`, so it knows which mail to read further. Pyrite stores only the matches. |
| IMAP reply detection | Your mail provider | Your credentials, to sign in read-only. Only message headers (sender, subject, date) are requested, never message bodies. |
| Industries tab, official numbers | The US Bureau of Labor Statistics (data.bls.gov) | Requests for its public employment tables. The area codes asked for show the metro area and state you set under `[market]`. The BLS sees your IP address and Pyrite's user agent. |
| Industries tab, outlook | Anthropic, through Claude Code, with web search and web fetch | The industry's name and codes, the metro area, state and country you set, the employers you follow in it, and the official numbers. Claude's searches and the pages it opens go to search providers and those sites. |
| Employer research | Anthropic, through Claude Code, with web search and web fetch | The employer's name, the job's title and the posting's link. Nothing about you. Claude's searches and the pages it opens go to search providers and those sites. The review links on the job's panel open a DuckDuckGo search, or the NLRB's case search, for the employer's name, and only when you click one. |
| Workday autofill | The employer's Workday site | What your answer sheet and tailored documents say, typed into a browser window you watch. Nothing is submitted. |
| Update available | GitHub, or wherever Pyrite's code folder was cloned from | A `git fetch` of `main`, once an hour while the dashboard is open, and the code itself when you click **Update and restart**. GitHub sees your IP address. Nothing about you is sent. `check_updates = false` under `[dashboard]` turns it off. |
| Building `.docx` and `.pdf` | LibreOffice or Word on your computer | Nothing leaves your computer. |

## Other people's information

Recruiter and employer mail can include other people's names and email addresses. Pyrite stores only the sender, subject and date of mail that looks like a reply to one of your applications, or that a scam rule flagged, and uses it only to show you that timeline. Delete what you don't want kept. If someone asks you to remove their details, remove the rows from your database.

## Your choices

- Each outside service is optional. Without Claude Code, the pan, dashboard and assay still work. Without mail settings, no mailbox is read.
- To remove everything, delete your workspace, and `~/.config/pyrite/imap.env` if you created it. Then sign out of Claude Code and revoke any Gmail connector or app password you set up for Pyrite.
- Your IMAP credentials live in `~/.config/pyrite/imap.env`, never in this repository or the workspace. Pyrite refuses that file until only your account can read it.

## Questions

Open an issue on this repository. Don't put personal details in it.
