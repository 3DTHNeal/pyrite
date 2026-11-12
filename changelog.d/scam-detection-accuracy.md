### Fixed

- **Possible scam** warnings no longer fire on a company's own shop and account mail. A company whose postings are on one domain, such as a `.jobs` site, can mail from its plain name at another ending, like `.com` or `.dev`, and that's no longer taken for a lookalike. Orders, returns and sign-in codes that name a company are left alone unless they're about hiring.

### Added

- The Gmail mail check now catches a cold pitch from someone who signs for a firm ("I run …", "founder @ …", "CEO of …") but writes from that firm's name with a word stuck on, or from a personal address. It also notices flattery like "based on your LinkedIn" and being told to check who they are on LinkedIn, and it reads the text of mail about contract work, hourly pay or a founder introducing themselves.
- The mail check also looks for these tells, taken from current FTC, FBI and security research:
  - **Lookalike addresses:** a domain that misspells a company (`contosso`, `c0ntoso`, `fabrikarn`), one that puts a company's address in front of someone else's domain (`contoso.com.hr-verify.example`), and one that borrows the name of a hiring system or job board (`greenhouse-careers`, `lnkedin`). It also catches a display name that shows an address other than the sender's.
  - **Fake coding tests:** the developer-targeted malware lure, where a stranger asks you to clone and run a repo or `npm install` a "coding test", paste a command into a terminal or press Win+R to "fix" a screening page, or update a camera driver.
  - **Money and phone codes:** reshipping and money-mule work, overpayments to send back, fees for background checks, certification or a starter kit, task-scam hooks like "recharge your account to unlock your earnings", and requests to pass on a verification code sent to your phone.
  - **Links:** more link shorteners, and pages on free hosts such as `vercel.app` and `netlify.app`.
