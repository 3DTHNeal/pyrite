# Reply detection

[All of the guide](README.md)

Commands use the Windows path `.venv/Scripts/python.exe`. Elsewhere, it's `.venv/bin/python`.

`pyrite inbox` runs after each morning pan. It reads the sender, subject and date of recent Gmail messages and compares them with every active job you've applied to. A match appears as **Possible reply** on the job's card, in the to-do list and on its timeline.

A match never changes a status, so a wrong one can't affect the response rate. Read the email, then use the usual buttons if it's real, or **Dismiss** if it isn't.

There are two ways to read the mailbox. IMAP with an app password is the plain one, and reads the text only of mail that matches an application. The Gmail connector in Claude Code needs no password on disk and also warns about job scams, at the cost of one short Claude run per pan. **Settings** on the dashboard, under **Mail**, picks between them and says whether the last read worked. It sets `source` and `lookback_days` under `[inbox]`, and the IMAP login stays in its own file, which Settings never shows or changes.

## Reading a possible reply

A match's text is read too, so you can work through the list without opening your mailbox for each one. In the to-do list, **Read its text** opens the start of the email under the line; the job's panel shows it under **Possible reply**. Each one is marked with what it looks like:

- **Looks like a rejection**: it says so in the usual words, such as "unfortunately", "we've decided to move forward with other candidates" or "the position has been filled". The panel offers **Log the rejection**.
- **Looks like a response**: someone wants to talk, schedule, interview, test or make an offer, or wrote something that's none of these. The panel offers **Log the reply** for a job still marked applied.
- **Receipts** never reach the list: "thanks for applying", "we've received your application", password resets and sign-in codes. A receipt that promises an interview "if your experience matches" is still a receipt. Words of a rejection or a response win over a receipt's, so mail that's both is shown rather than left out.

The mark comes from plain rules on the subject and text, not from a model, so read the text before you log anything. With only the subject to go on, as with "Thank you for your interest" when the text couldn't be read, there's no mark at all.

Whoever sent an email wrote every word of it, so its text is treated as hostile:

- It's plain text before it's kept. HTML is reduced to the words a reader would see: scripts, styles and text hidden with CSS are dropped, and so are zero-width, direction-changing and control characters.
- Every link becomes the name of its site, such as `[link to careers.contoso.com]`. The address itself, with any tracking token in it, never reaches the dashboard, and nothing in the text can be clicked.
- The quoted history under a reply, and unsubscribe footers, are cut, and what's left is held to 1,500 characters.
- The dashboard draws it as text only, so markup in an email can't run on the page, and it's never handed to Claude.
- It's kept beside the timeline, not in it, and cleared 30 days after it was read. What the mail looked like stays; the mailbox keeps the original. A scam warning's text goes as soon as you dismiss it.

## Through the Gmail connector

Set `source = "gmail"` under `[inbox]` in `search.toml`. Each pan then starts Claude Code for one narrow job: copy the sender, subject, date and snippet of recent mail, and a little of the text of mail about hiring, into one JSON list that it hands back as its closing message. That run gets only the Gmail `search_threads` and `get_message` tools, and no tool that writes, so it can't send, reply, label or delete anything, or touch a file on this machine, whatever an email tells it. The Gmail tools that send or change mail are also denied by name, so a workspace `.claude/settings.json` can't allow one. Claude only carries the list; it isn't taken at its word. A message it hands back is kept only if Gmail's own search results in that run hold it, from the sender Claude names, so an email asking Claude to list it as from an employer is left out, and the pan's report says how many were. Its snippet and text are kept only where they're what Gmail returned for that very message, so one email can't have Claude put its words under an employer's: text that doesn't match is left out, the message is judged by its headers alone, and the report says how many lost theirs. A run that called any tool besides the two Gmail reading ones, or handed back two lists, isn't used at all. The run is told the companies you've applied to and those under `[inbox.domains]`, never every company a board listed. A run that couldn't read the mail, whether it says so, hands back a list that was cut off, or wraps an empty list in a sentence, counts as a failed check, so the next one reads the same days again. So does a run that started without the Gmail tools: Claude Code is told to wait for its connectors before the first turn, and a start that still finds Gmail not yet connected is tried once more 30 seconds later. A connector that needs signing in again, or isn't set up, is named on the Sources tab rather than retried. The list is thrown away once judged. Only a possible reply or a scam warning keeps the start of its text, made safe as [above](#reading-a-possible-reply). Only the Primary and Updates categories are read, since that's where replies and recruiter mail land, mail from job boards such as LinkedIn and Indeed is left out of the search, since an alert is never a reply, and the text of a message is read only when it's about hiring, or when it comes from an employer or applicant tracking system and names a company you've applied to. A job board's is never read, and Claude may read up to ten messages in one turn. Reading a reply's text costs a little more than the headers alone; a later run reads back only a couple of days, so it stays a few messages. Plain code does the matching above, and the scam check below. The run is counted under **Checking mail** on the [Claude usage](schedule.md#claude-usage) panel. It uses Sonnet, since copying headers needs no judgment; `model` under `[inbox]` picks another. The first read of a week or two of mail is the longest and dearest one, since later runs only read back a couple of days past the last good one.

Setup: connect Gmail under Connectors in the Claude desktop app, sign in once with `claude auth login` in a terminal outside the app, and test it:

```bash
.venv/Scripts/python.exe tools/pyrite.py inbox
```

A Claude session that has read Gmail itself can also hand over an export in the same shape as `tools/pyrite/mail_check.md` describes, with `pyrite inbox --from <file.json>`.

**Scam warnings** appear as **Possible scam** at the top of the to-do list, with a **Possible scam** mark on the card of any job whose company the mail names, and the reasons in plain words. Only mail about hiring, or mail that names a company Pyrite has seen, is looked at. Mail about contract work, a rate by the hour, a coding test or a founder introducing themselves counts as hiring mail, and through Gmail its text is read. An order, a return or a sign-in code that names a company is left alone unless it's about hiring.

One strong sign is enough:

- **An address that isn't the company's.** A domain that looks like the company's but isn't, including one spelled with letters from another alphabet, one that misspells it (`contosso`, `c0ntoso`, `fabrikarn`), one that puts the company's address in front of someone else's domain (`contoso.com.hr-verify.example`), and one that borrows the name of a hiring system or job board (`greenhouse-careers`, `lnkedin`). Once the company's own domains are known, its name at another ending, such as `contoso.top` beside `contoso.com`, is a lookalike too. A company whose postings are on one domain, such as a `.jobs` site, may mail from its plain name at an ordinary ending like `.com` or `.dev`, so that isn't, unless the ending is one anyone registers for a few cents. A display name that shows another address than the sender's counts here too.
- **A personal address claiming to be the company**, or replies routed to a personal address. So does someone signing for a firm ("I run …", "founder @ …", "CEO of …") from a personal address; from the firm's name with a word stuck on, it's a weaker sign.
- **An interview over a chat app**, such as WhatsApp or Telegram, or a link to one.
- **Money:** gift cards, checks, wire transfers, crypto, bank details, fees for training, a background check, certification or a starter kit, being asked to buy equipment, reshipping goods or passing money through your account, an overpayment to send back, and task-scam hooks such as "recharge your account to unlock your earnings".
- **A code sent to your phone**, asked to be passed on, since it opens your accounts.
- **A fake coding test:** a stranger asking you to clone and run a repository or `npm install` a "coding test", to paste a command into a terminal or press Win+R to "fix" a screening page, or to update a camera driver. This is how developer-targeted malware gets installed.

Weaker signs need two together: "you've been selected" wording or flattery such as "based on your LinkedIn", pressure to act within hours, being told to check who they are on LinkedIn rather than a company site, a link shortener, a page on a free host such as `vercel.app` or `netlify.app`, a form to fill in, or a passport, date of birth or travel refund mentioned with no money or chat app beside it. Mail from the company's own domain or a known applicant tracking system gets the benefit of the doubt on wording, because a real offer also mentions deadlines and ID checks; signing for a company never earns it, since anyone can register a domain to match the name they sign with. The rules draw on current FTC, FBI and security research on job scams. A warning changes nothing. Open the mail yourself, don't reply, click, run or pay, and **Dismiss** it if it turns out to be genuine.

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

An app password opens the whole mailbox as far as Google is concerned. The read-only behavior comes from this code, which opens folders with `readonly=True`, asks for headers first, and reads the start of a message's text, with `BODY.PEEK` so it isn't marked read, only when the message matches an application. To cut off access, revoke the password on the same Google page.

**What counts as a match:**

- Mail from the company's own domain, including subdomains. If an employer uses a domain that doesn't match its name, add it under `[inbox.domains]` in `search.toml`.
- Mail from an applicant tracking system such as Greenhouse or Workday, if the company is named as a whole word in the sender name or subject.

**What it can miss or get wrong:**

- It misses outside recruiters, personal addresses, LinkedIn messages and anything in Spam. Keep reading your email.
- The scam rules work from patterns, so they miss a scam that uses none of the usual tells and can flag a blunt recruiter. They're a prompt to look closer, not a verdict.
- Automatic mail isn't a reply, so it's left out: "thanks for applying" receipts, password resets and sign-in codes, and mail from an employer's shop, such as an order, a delivery or a return. Mailing-list mail is skipped unless its subject is about hiring. "Thank you for your interest" is a receipt as often as a rejection, so it's left out only when its text says neither. When the text couldn't be read, it's flagged.
- If you've applied to two roles at one company, a match appears on both, unless its subject names one of their titles. A subject that names another job there, such as one already closed, goes on none of them.
- Sender names can be forged. Treat a match as a prompt to open your mailbox. The text the dashboard shows has no links to follow, by design: go to the employer's site yourself.

If the login or connection fails, the pan still succeeds and **Email replies** shows as failing on the Sources tab.
