# Finding and ranking postings

[All of the guide](README.md)

Commands use the Windows path `.venv/Scripts/python.exe`. Elsewhere, it's `.venv/bin/python`.

## Adding companies

Add a line under `[watch.*]` in `search.toml` if the careers page is on Greenhouse, Lever, Ashby or Workday, then run `pyrite sources` to confirm it responds. Employers with no public feed go under `[[manual_check]]`, which lists them on the dashboard's Sources tab. Use **Add a posting** for anything you find yourself, such as on LinkedIn.

## Going through prospects

**Tailor** and **Pass** sit on each row of Prospects, so a quick no doesn't need the panel. The panel's header shows the job's number, which the `pyrite` commands take, and while it's open the address ends in `#job-` and that number, so the link opens the same job again. In the job panel, **J** and **K** step through the list you opened it from, and on a job nothing has been written for yet, **T** tailors it and **P** passes, then the next one opens. A pass shows **Undo** for ten seconds, and a passed job that hadn't been sent offers **Undo pass**, which puts it back where it was. A ready draft is only passed with the button, never a key. The first time you open a prospect it's marked as looked at; the Prospects count says how many you haven't opened, and **Not looked at yet** filters to them.

## New listings, reposts and possible ghost jobs

Prospects, the to-do list and the daily run put the newest listings first, ahead of older ones with a similar score. **Priority** is the filter score plus points for age and for a preferred city or industry, minus a penalty for each repost. The weights are under `[freshness]` and `[promote]` in `search.toml`. Priority only changes the order, and the filter score still decides what's kept and tailored.

- **New:** posted in the last 7 days, never reposted, seen by the latest pan, and with nothing else on this list against it.
- **Reposted:** the same job came back under a new listing, or the same listing came back after being taken down. The same job in another city isn't a repost. Age keeps counting from the earliest date on record, so a repost doesn't look new again. A board can also move a date forward without a pan seeing it happen, so a listing is never younger than the day a pan first found it.
- **Re-dated:** a board moved a listing's posted date forward. Only Workday and Ashby are checked, since Greenhouse and Lever report the date a listing was created.
- **Possible ghost:** up 90 days or more, reposted or re-dated twice, or reposted and up 45 days or more. The posting's own words count too: "an evergreen role we keep open on an ongoing basis", or "a pipeline role". It's a prompt to look closer, not proof: some companies keep real openings up all year. A listing with no date that a pan first found 90 days ago or more counts as up that long.
- **Not rechecked:** the latest full pan didn't see the listing. Its board failed, you took the board off your watch list, or Workday didn't answer about it in time. It may be down.
- **Possible scam:** the posting asks you to pay a fee, to talk or interview over WhatsApp, Telegram, Signal or WeChat, or says it will send you a check. A posting that says it would never do these things is warning you about scams, so it doesn't count. Postings on a company's own board almost never do this; a posting you added yourself might. It also goes on the to-do list.
- **May be a repost:** a Workday link ending in `-1` or similar, which often means a requisition has more than one posting. It's a hint only and costs no priority.

**Only listings that look real**, under Show on Prospects, hides possible ghosts, scams and listings not rechecked.

Some postings aren't openings at all, and a pan drops them as it drops a title or place you don't want: a "General Application", "Expression of Interest" or "Talent Community", or a posting that says it has no open position right now. So does a posting with a scam's tells. `pyrite rescore` drops ones already on your list that you haven't acted on. These checks were tried against about 9,000 postings from real boards, and ordinary phrases that share a word, such as "evergreen content", "building a talent pipeline" or "applications are reviewed on a rolling basis", don't count.

A board's first pan sets a baseline, so repost counts stay at zero until a later pan sees something come back.

Two postings count as one job only when their text nearly matches throughout, so openings that share a title and an "about us" paragraph stay separate. On Workday, two postings under the same requisition id with mostly the same title are one job too, since a repost there often comes back rewritten under the old id with `-1` added. Titles are compared with short forms spelled out, so "Sr. Firmware Engr" is "Senior Firmware Engineer". Workday's search returns only some of a site's postings, so each pan asks it directly about the tracked ones it left out. A posting is marked down only when Workday confirms it's gone, and one it confirms is still up isn't mistaken for a repost when the same job appears in another city.

## Pay, rarity and asks nobody could meet

Pyrite reads a few more things into each posting, in plain code, and shows them as tags on the card and under **What Pyrite read into it** in the job panel. Pay and rarity add to Priority; none of them change the filter score.

- **Pay.** The posting's range, read the way boards write it and turned into a year's pay, against what the position pays, not against what you'd take: the median middle of the ranges Pyrite has seen for the same track at the same level, widening to the whole track and then every track until there are five to compare with. When even the top of the range is under 75% of that, it's **Too low to bother**: it sinks in priority and the daily run doesn't spend Claude judging it unless you pick it. A middle under 80% is **Pays under the going rate**, and 1.4 times or more is **Pays well above similar roles**, which often means the job is a level above its title, a range set for a high-cost city, or a typo. A range whose top is more than 1.8 times its bottom is a **Wide range**, which spans levels. A range in another currency than `currency` under `[pay]` isn't compared.
- **Rare near you.** A local role in a track Pyrite has seen at most `rare_max` other local postings of (2 if unset) in 90 days earns `rare_points` under `[freshness]`. Remote roles never count, and it waits until Pyrite has been checking boards for 30 days. It only knows the boards you watch and the postings your filters kept.
- **Asks the impossible.** "8+ years building AI agents" can't be met, since LLM agents haven't existed that long. Pyrite reads each "N years" in a posting and the skill it's about, and checks it against when that skill became usable by anyone. An ask for more years than that is shown as an ask nobody could meet, not as your gap: a "check before applying" line from the notes that only restates it moves off **Before you apply**, and Claude is told when it judges and tailors the posting, along with how long each young skill has existed, so your experience is weighed against the skill's whole life. The dates are the earliest fair ones and nothing is rounded in the posting's favour, and the posting's own words are kept with each ask, since a sentence can name two skills. `pyrite skills` lists the skills Pyrite knows and their ages. With `research = true` under `[skills]`, the daily run has Claude look up the skills postings ask years of that Pyrite doesn't know, on the web and with the same source check as the industry outlook, keeping only dated answers whose source it found, in `data/skill-ages.json`. `pyrite skills --research` does that for the postings waiting now, and `pyrite skills "<skill>"` for one you name.

## Preferred cities and industries

Open the dashboard's **Settings** tab to choose the cities and industries you want to see first. A match adds to Priority and shows as a teal tag on Prospects, whose **Preferred city or industry** filter lists only those postings. Open a job to see the points under **Why its priority is**.

The tab has a panel for the points, one for cities and a card for each industry, and each has its own **Save**. A save writes only that panel's part, so an edit you haven't finished in another panel isn't saved with it. Industry cards stay closed until you open one, and show what's saved in a line.

In the Cities panel, start typing and the name box suggests places your own postings name, with how many postings each has. Beside each city it shows how many prospects the name matches right now, and how the job boards write the place, which is how you spot a city that shares its name with one in another state.

The tab edits only `[promote]` in `search.toml`, which you can also edit by hand. A save rewrites that section and its comments, leaves the rest of the file alone, and keeps the earlier file in the Profile tab's History, where **Put back** restores it. Filters, the patterns under `[guard]` and allowed hosts can't be changed from the dashboard, because it has no login. The demo can't save settings.

- **Cities** match the posting's location, as a whole word. Add `match` if the name alone isn't enough, as when another state has a city with the same name.
- **Industries** have no field on a job board, so they're judged from the posting. It counts if the employer is under `companies`, a term is in the employer's name or the title, or the terms appear at least `mentions_needed` times in the description. One passing mention doesn't count, and terms need to be specific, since "medical" alone would catch most postings' benefits text.
- **Points** are `city_points` and `industry_points`, and any line can override them with `points`. Each list counts once, at its best match.
- **Tracks can be limited to industries.** A `[[track]]` with `industries = ["Robotics"]` matches only postings in those industries, judged the same way. Use it for a broad title, such as plain "software engineer", that you want only from the employers you care most about.
- **Skills it wants** are what an industry looks for. The tab checks them against `facts.md`, skipping its "Do not use" and "Unsupported" sections, and shows what you have and what's missing. It's a word match to help you set the points, so it doesn't change the ranking or what a resume may claim. If a gap is true of you, add it to `facts.md` first.

Promotions change the order and nothing else. They raise no filter score, so a posting below `tailor_min_score` still won't be tailored, and they can't bring back a posting the filters dropped. To accept a new city at all, add it under `[location]` too. The daily run works through its limit in Priority order, so promoted postings do get read first.

Changes apply the next time the dashboard refreshes, and need no `rescore`.

## Industries

The **Industries** tab shows how each industry under `[promote]` is doing where you live, in three parts.

- **In your search** is what Pyrite has seen: postings in the last 90 days that passed your filters and count as the industry (judged as under [Preferred cities and industries](#preferred-cities-and-industries)), how many are still listed, local against remote, the employers posting most, and what came of applying. Only postings Pyrite has seen count, so it's thin for the first weeks.
- **Official numbers** come from the BLS [Quarterly Census of Employment and Wages](https://www.bls.gov/cew/), which counts nearly every job from employers' unemployment insurance filings. For your metro area, your state and the country, it shows private-sector jobs, their change over a year, workplaces, average weekly pay against all private jobs in the same area, and concentration (above 1 means the industry is a bigger share of jobs there than nationally). It's solid but runs five to six months behind, and a metro area's industry detail comes out a quarter or two after a state's, so each row names its quarter. The BLS withholds a figure that would reveal one employer's numbers, and the tab says which codes were left out. US only.
- **Outlook** is written by Claude from a web search, when you click **Research with Claude**. It covers hiring and layoffs, investment, the employers nearby, headwinds and what it means for a job search, with every point linked to its source. Like the skill lookup, it's a Claude run with web access and nothing else: no files and no shell, and nothing about you beyond the industry, the area and the employers you listed. Plain code then keeps only the points whose sources are pages that run opened or its searches listed, matched on the whole address rather than a site's home page or a link some other page mentioned, and says how many it dropped. That can't prove a page says what a point claims, so open the source before relying on it. `pyrite outlook "<industry>"` does the same from the command line. It uses Sonnet unless `model` under `[market]` says otherwise.

To set it up, give each industry its codes on the Settings card, under **Industry codes (NAICS)**, or as `naics = ["334413", "333242"]` in `search.toml`. Look codes up at [census.gov/naics](https://www.census.gov/naics/). Codes are broad, so pick the narrowest that fit, and don't list one inside another, since its jobs would count twice. Then name where you live:

```toml
[market]
state = "Wisconsin"    # the full name
metro = "Madison, WI"  # as the BLS writes it, without "MSA"
```

The numbers are read from data.bls.gov when the tab opens and kept in `data/market/`, then looked for again after a week. No key or account is needed.
