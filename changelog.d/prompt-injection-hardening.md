### Security

- A posting can no longer close the fence around its text by writing the closing tag with attributes, a zero-width space, fullwidth brackets or `&lt;`. Every spelling of a tag named `untrusted…` is neutralized, for every fence Pyrite uses.
- Drafts, notes and interview briefs, which a run wrote after reading the posting, now go back to the next run fenced as data, and so do the fact checker's findings that quote them. They no longer read as Pyrite's own instructions.
- Tailoring can read only its own job's folder. A posting can no longer have it read another application's notes, say, and name in a letter the other companies you're talking to. The prompt already carried every file it needs.
- Web research for Industries, employer research and skill ages starts in an empty folder, so the workspace's CLAUDE.md and git history, which name the employers you've applied to, aren't in the context of a run that can fetch any page.
- Judging a posting counts a reply holding two verdicts as no verdict, rather than taking the last one, which a posting could write for Claude to copy. Braces quoted in a reason no longer lose the verdict.
- The assay reads a draft as it prints: an HTML comment inside a word or number (`ph<!---->d`, `4<!---->4`) no longer gets it past the confidential, claims and number checks. Autofill leaves comments out too.
- A job board title or company name too long, or holding too many numbers, to be only a name no longer exempts its numbers and terms when a draft repeats it. A short number a posting calls its job id is let through in a letter only beside a label, so "Job ID: 40000" no longer approves "$40000".
- The Gmail mail check keeps only messages that Gmail's own search returned, from the sender Claude names. An email asking Claude to list it as from the employer is left out, and the sweep's report says how many were. A run that called any tool besides the two Gmail reading ones, or handed back two lists, isn't used.
- Mail from a company's name at another ending, such as contoso.top when contoso.com is known, is now warned about as a lookalike rather than taken for the company.
- Invisible characters are stripped from a posting's title, company, location, workplace, link and pay, as they already were from its description. `pyrite job` prints the company inside the posting's fence.
