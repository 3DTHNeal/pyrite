### Added

- **Possible reply** and **Possible scam** show the start of the email's text: **Read its text** in the to-do list, and under **Possible reply** in the job's panel. It's plain text with hidden text, scripts and invisible characters removed, each link shown only as the name of its site, and the quoted history and footer cut. It's never handed to Claude, and it's cleared after 30 days, or when you dismiss a scam warning.
- A possible reply is marked **Looks like a rejection** or **Looks like a response**, and the job's panel offers **Log the rejection** or **Log the reply** to match. It's a guess from plain rules on the words, and changes nothing until you press a button.

### Changed

- Receipts are told apart by their text as well as their subject, so "Your application to Contoso" over "we've received your application" no longer shows as a possible reply. A receipt's "if you're selected, we'll schedule an interview" doesn't count as an answer.
- Over IMAP, a message that matches an application now has the start of its text read, with `BODY.PEEK` so it isn't marked read. Other mail is still read by its headers alone.
- Through the Gmail connector, mail from an employer or applicant tracking system that names a company you've applied to now has its text read, so a reply has something to show.

### Security

- Through the Gmail connector, a snippet or text that Claude copied is kept only if it's what Gmail returned for that very message, so one email can't have Claude put its words under an employer's message.
