# Reply detection

[All of the guide](README.md)

Commands use the Windows path `.venv/Scripts/python.exe`. Elsewhere, it's `.venv/bin/python`.

`pyrite inbox` runs after each morning pan. It reads the sender, subject and date of recent Gmail messages and compares them with every active job you've applied to. A match appears as **Possible reply** on the job's card, in the to-do list and on its timeline.

A match never changes a status, so a wrong one can't affect the response rate. Read the email, then use the usual buttons if it's real, or **Dismiss** if it isn't.

There are two ways to read the mailbox. IMAP with an app password is the plain one and never downloads a message body. The Gmail connector in Claude Code needs no password on disk and also warns about job scams, at the cost of one short Claude run per pan. **Settings** on the dashboard, under **Mail**, picks between them and says whether the last read worked. It sets `source` and `lookback_days` under `[inbox]`, and the IMAP login stays in its own file, which Settings never shows or changes.

## Through the Gmail connector

Set `source = "gmail"` under `[inbox]` in `search.toml`. Each pan then starts Claude Code for one narrow job: copy the sender, subject, date and snippet of recent mail, and a little of the text of mail about hiring, into one JSON list that it hands back as its closing message. That run gets only the Gmail `search_threads` and `get_message` tools, and no tool that writes, so it can't send, reply, label or delete anything, or touch a file on this machine, whatever an email tells it. The Gmail tools that send or change mail are also denied by name, so a workspace `.claude/settings.json` can't allow one. The run is told the companies you've applied to and those under `[inbox.domains]`, never every company a board listed. A run that couldn't read the mail, whether it says so, hands back a list that was cut off, or wraps an empty list in a sentence, counts as a failed check, so the next one reads the same days again. So does a run that started without the Gmail tools: Claude Code is told to wait for its connectors before the first turn, and a start that still finds Gmail not yet connected is tried once more 30 seconds later. A connector that needs signing in again, or isn't set up, is named on the Sources tab rather than retried. The list is thrown away once judged, so message text never stays on disk or in the database. Only the Primary and Updates categories are read, since that's where replies and recruiter mail land, mail from job boards such as LinkedIn and Indeed is left out of the search, since an alert is never a reply, and the text of a message is read only when it's about hiring and comes from somewhere other than a known employer, applicant tracking system or job board. That last rule is what keeps the run cheap: a confirmation from Workday is judged from its subject and snippet alone. Plain code does the matching above, and the scam check below. The run is counted under **Checking mail** on the [Claude usage](schedule.md#claude-usage) panel. It uses Sonnet, since copying headers needs no judgment; `model` under `[inbox]` picks another. The first read of a week or two of mail is the longest and dearest one, since later runs only read back a couple of days past the last good one.

Setup: connect Gmail under Connectors in the Claude desktop app, sign in once with `claude auth login` in a terminal outside the app, and test it:

```bash
.venv/Scripts/python.exe tools/pyrite.py inbox
```

A Claude session that has read Gmail itself can also hand over an export in the same shape as `tools/pyrite/mail_check.md` describes, with `pyrite inbox --from <file.json>`.

**Scam warnings** appear as **Possible scam** at the top of the to-do list, with a **Possible scam** mark on the card of any job whose company the mail names, and the reasons in plain words. Only mail about hiring, or mail that names a company Pyrite has seen, is looked at. One strong sign is enough: a domain that looks like the company's but isn't (including one spelled with letters from another alphabet), a personal address claiming to be the company, replies routed to a personal address, an interview over WhatsApp or Telegram, or any mention of gift cards, checks, fees, crypto or bank details. Weaker signs, such as "you've been selected" wording, pressure to act within hours, link shorteners, a form to fill in, or a passport, date of birth or travel refund mentioned with no money or chat app beside it, need two together. Mail from the company's own domain or a known applicant tracking system gets the benefit of the doubt on wording, because a real offer also mentions deadlines and ID checks. A warning changes nothing. Open the mail yourself, don't reply, click or pay, and **Dismiss** it if it turns out to be genuine.

## Through IMAP

**Setup.** Until this is done, the command says it isn't set up and exits cleanly.

1. Create an app password at <https://myaccount.google.com/apppasswords>, which needs 2-Step Verification turned on.
2. Create the credentials file. It lives outside this repository, and the command refuses to use it if other users can read it. On Windows it checks the file's access list, and a file created in your home folder is private by default.

   ```bash
   mkdir -p ~/.config/pyrite && cp tools/pyrite/imap.env.example ~/.config/pyrite/imap.env
   ```

3. Open `~/.config/pyrite/imap.env` and fill in `IMAP_USER` and `IMAP_PASSWORD` yourself.
4. Test it. With no applications logged yet it still checks the login.

   ```bash
   .venv/Scripts/python.exe tools/pyrite.py inbox
   ```

An app password opens the whole mailbox as far as Google is concerned. The read-only behavior comes from this code, which opens folders with `readonly=True` and only asks for headers. To cut off access, revoke the password on the same Google page.

**What counts as a match:**

- Mail from the company's own domain, including subdomains. If an employer uses a domain that doesn't match its name, add it under `[inbox.domains]` in `search.toml`.
- Mail from an applicant tracking system such as Greenhouse or Workday, if the company is named as a whole word in the sender name or subject.

**What it can miss or get wrong:**

- It misses outside recruiters, personal addresses, LinkedIn messages and anything in Spam. Keep reading your email.
- The scam rules work from patterns, so they miss a scam that uses none of the usual tells and can flag a blunt recruiter. They're a prompt to look closer, not a verdict.
- It flags automatic "we received your application" notices, and non-marketing mail from a company you also buy from. Mailing-list mail is skipped unless its subject is about hiring.
- If you've applied to two roles at one company, a match appears on both.
- Sender names can be forged. Treat a match as a prompt to open your mailbox, and don't follow links from the dashboard's text.

If the login or connection fails, the pan still succeeds and **Email replies** shows as failing on the Sources tab.
