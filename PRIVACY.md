# Privacy

Pyrite has no server, account or telemetry. It sends nothing to its author. Everything it keeps stays in your workspace on your own computer. Some features do send data to outside services, and this page lists each one so you can decide which to turn on.

## What stays on your computer

Your workspace (the folder `PYRITE_HOME` points to) holds:

- your profile: the fact bank, approved terms, run notes, search settings and Workday answer sheet;
- each application's posting, drafts, notes, built documents and autofill log;
- `data/pyrite.db`: jobs, statuses, timelines, the run log, the time, tokens and estimated cost of each Claude run, and, for possible replies and scam warnings, the sender, subject and date of matching mail.

The dashboard listens on localhost only. Nothing on it is reachable from another machine unless you set that up yourself.

## What goes where

| Feature | Sent to | What's sent |
|---|---|---|
| Morning pan | Each job board you list | Ordinary requests for public job feeds. The board sees your IP address and Pyrite's user agent. Nothing about you is sent. |
| Triage, drafting, Refresh resume, interview prep | Anthropic, through Claude Code | The posting, and for drafting, refreshes and prep, your fact bank, run notes, approved terms, model documents and existing drafts. Anthropic's terms and privacy policy apply, under your own account. |
| Gmail connector | Google and Anthropic, through Claude Code | Claude reads recent mail through your connected Gmail account and returns the sender, subject, date and a short snippet of each. Pyrite stores only the matches. |
| IMAP reply detection | Your mail provider | Your credentials, to sign in read-only. Only message headers (sender, subject, date) are requested, never message bodies. |
| Workday autofill | The employer's Workday site | What your answer sheet and tailored documents say, typed into a browser window you watch. Nothing is submitted. |
| Building `.docx` and `.pdf` | LibreOffice or Word on your computer | Nothing leaves your computer. |

## Other people's information

Recruiter and employer mail can include other people's names and email addresses. Pyrite stores only the sender, subject and date of mail that looks like a reply to one of your applications, or that a scam rule flagged, and uses it only to show you that timeline. Delete what you don't want kept. If someone asks you to remove their details, remove the rows from your database.

## Your choices

- Each outside service is optional. Without Claude Code, the pan, dashboard and assay still work. Without mail settings, no mailbox is read.
- To remove everything, delete your workspace, and `~/.config/pyrite/imap.env` if you created it. Then sign out of Claude Code and revoke any Gmail connector or app password you set up for Pyrite.
- Your IMAP credentials live in `~/.config/pyrite/imap.env`, never in this repository or the workspace. Pyrite refuses that file until only your account can read it.

## Questions

Open an issue on this repository. Don't put personal details in it.
