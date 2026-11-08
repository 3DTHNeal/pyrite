# End-User License Agreement

Pyrite is open-source software. Your right to use, copy, modify and distribute it comes from the [MIT License](LICENSE), and nothing here takes any of that away. This agreement explains what you're responsible for when you run Pyrite, and what it doesn't promise. If the two ever conflict about what you're allowed to do with the code, the MIT License wins.

By running Pyrite you agree to the terms below. If you don't agree, don't run it.

## 1. What Pyrite is

Pyrite is a tool for one person's job search. It reads public job boards, ranks postings, has an AI model draft resumes and cover letters, checks those drafts against a fact bank you write, and shows the results on a dashboard on your own computer. Optional features read your mailbox for replies and fill in Workday application forms.

Pyrite never submits an application. You decide what to send, and you send it.

## 2. You're responsible for what you send

- **Truthfulness.** Pyrite's fact checker, the assay, works from patterns and from your fact bank. It can miss a false or misleading statement, and it can only be as accurate as the fact bank you give it. Read every document before you use it. Anything you send to an employer is your own statement, and you're responsible for it being true.
- **AI output.** Drafts, triage verdicts, interview prep briefs and scam warnings are produced in part by an AI model. They can be wrong, incomplete or out of date. Treat them as suggestions.
- **Forms you fill in.** Workday autofill types what your answer sheet says. Check every page before you continue, including answers about work authorization, sponsorship, background and demographics. Pyrite stops before voluntary disclosures and never presses a button that submits.

## 3. Third-party sites and services

Pyrite connects to services it doesn't control. Each has its own terms, and you're responsible for following them.

- **Job boards.** Pyrite reads public feeds from Greenhouse, Lever and Ashby, and the JSON behind Workday's public careers pages. Read each site's terms and keep your request volume reasonable. Don't point Pyrite at a site whose terms forbid automated access.
- **Workday autofill.** It's experimental and off by default. Some employers and sites don't allow automated form filling. Check before you turn it on, and don't use it to get around a CAPTCHA, a rate limit or any other control.
- **Claude Code.** Drafting, triage, refreshes, interview prep and the Gmail connector run through Claude Code, under your own Anthropic account and Anthropic's terms. You pay for that usage. The cost estimates on the dashboard are estimates, not a bill.
- **Mail.** Reply detection signs in to your mailbox with credentials you provide, read-only. You're responsible for keeping those credentials safe and for having the right to read that mailbox.

[PRIVACY.md](PRIVACY.md) explains what data goes to which service.

## 4. Acceptable use

Don't use Pyrite to:

- send applications, messages or documents that you know are false or misleading;
- apply as, or draft documents for, someone else without their permission;
- collect personal information about recruiters, employees or other candidates beyond what Pyrite records about replies to your own applications;
- overload, scrape against the terms of, or get around access controls on any website;
- break any law that applies to you, including employment, privacy, anti-discrimination and computer-misuse laws.

## 5. Not advice

Pyrite and its documentation, including [the resume playbook](docs/resume-playbook.md), are general information about job searching and application systems. They aren't legal, immigration, tax, financial or career advice. The playbook summarizes outside sources that can be wrong or out of date. Pyrite's scam warnings can miss a scam and flag a real recruiter, so verify an employer independently before you share documents, ID or bank details, or pay anything.

## 6. Your data

Pyrite runs on your computer and has no server of its own. It sends nothing to its author. You own your fact bank, documents, database and settings, and you're responsible for backing them up. The database in your workspace can't be rebuilt from anything else.

## 7. No warranty

Pyrite is provided "as is", without warranty of any kind, as the MIT License says. There's no guarantee that it works, that it finds every posting, that the assay catches every error, that it detects every reply or scam, or that using it will get you an interview or a job.

## 8. Limitation of liability

To the fullest extent the law allows, the authors and copyright holders aren't liable for any claim, damages or other liability arising from Pyrite or from using it. That includes a rejected or withdrawn application, an offer that's lost or rescinded, a statement in a document you sent, a missed reply or deadline, a scam, a suspended account on any third-party service, fees charged by a third-party service, and lost or damaged data.

## 9. Trademarks

Greenhouse, Lever, Ashby, Workday, LinkedIn, Gmail, Google, Claude, Claude Code, Anthropic, Microsoft Word and LibreOffice are trademarks of their owners. Pyrite names them only to say what it works with. It isn't affiliated with, endorsed by or sponsored by any of them. The companies and people in `example/` are fictional.

## 10. Contributions

Unless you say otherwise in writing, anything you contribute to this repository is licensed under the MIT License, the same as the rest of it.

## 11. Changes and ending

These terms can change with any commit to this repository. The version that applies is the one in the copy you run. They end when you stop using Pyrite and delete your copies. Sections 2, 5, 7 and 8 continue after that.

## 12. Severability

If any part of this agreement can't be enforced, the rest still applies.
