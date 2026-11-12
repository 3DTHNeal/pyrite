### Fixed

- **Possible scam** warnings no longer fire on a company's own shop and account mail. A company whose postings are on one domain, such as a `.jobs` site, can mail from its plain name at another ending, like `.com` or `.dev`, and that's no longer taken for a lookalike. Orders, returns and sign-in codes that name a company are left alone unless they're about hiring.

### Added

- The Gmail mail check now catches a cold pitch from someone who signs for a firm ("I run …", "founder @ …", "CEO of …") but writes from that firm's name with a word stuck on, or from a personal address. It also notices flattery like "based on your LinkedIn" and being told to check who they are on LinkedIn, and it reads the text of mail about contract work, hourly pay or a founder introducing themselves.
