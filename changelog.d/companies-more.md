### Added

- **Companies to watch** reads more careers page addresses: Workday's `myworkdaysite.com` addresses, Lever's EU site `jobs.eu.lever.co`, and Ashby boards whose names have spaces. A Lever board on the EU site is written `acme = { name = "Acme", eu = true }` and read from Lever's EU feed. A Workday site on a company's own domain is refused with a message saying why, rather than "isn't one of them".
- **Pages per search** under **Workday searches** sets `[workday] max_pages` from the dashboard, from 1 to 10, and says what raising it costs: each page is a request to every watched Workday site.

### Fixed

- **Check by hand** under **Companies to watch** changes each company where it is in `search.toml`, so comments between the entries stay. A new one goes after the last, and a list emptied and filled again stays where it was.
