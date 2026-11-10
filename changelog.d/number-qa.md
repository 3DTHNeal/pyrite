### Fixed

- Pay is no longer judged partly against itself: the going rate a posting is compared with is the median of the other postings like it.
- "Manager" in a Product, Program or Account Manager's title no longer makes the job senior-most for pay, and an entry-level title is compared only with other entry-level ones. **Too low to bother**, which keeps the daily run from judging a job, now needs postings at the job's own level to compare with. Against a whole track, which mixes levels, a range can only be under the going rate.
- Pay ranges keep the period and currency written beside them: "$12,000 - $15,000 per month" is a year's $144k–$180k, not $12k–$15k, "$400 a day" is no longer read as an hourly rate, "CAD" and "MX$" ranges aren't taken for US dollars, and a contractor's hourly rate later in the text no longer turns a salary into an hourly one. "Between $132,000 and $198,000" is read, a sign-on bonus written before the pay isn't taken for it, and a range missed when a job was found is read from its description.
- Lever pay keeps its currency and how often it's paid.
- Posting ages count days where you are: a posting published at midnight UTC went up the day before in the Americas, so it's no longer a day younger than it is.
- A notes deadline that restates a posting's "at least until" date no longer makes it firm and passes on the job. "Relocate no later than March 1" is no longer a deadline, "or once filled" makes a date a floor, and a date with no year, such as "until December 1", is read as the nearest one but never passes on a job by itself.
- Gaps named only by a category, such as **Domain** or **Scale**, are grouped by what follows the name, so nine unrelated "Domain" gaps no longer count as one question.
- A Claude run stopped for running out of time counts the tokens it had used, and the cost shows with a **+** when it leaves such a run out. An industry outlook whose sources all failed the check counts as a failed run, skill-age research is labelled **Skill ages**, and the usage note lists every kind of run counted.
- **Ready to send** counts only drafts whose posting is still up, and its tooltip says how many to check again and how many came down. The funnel still has every job at its stage.
- A board taken out of `search.toml` leaves the Sources tab instead of staying there as working.
- **Reach out**'s list of other employers adds up to the count it gives, and a follow-up no longer says "1 days".
- Token counts and sizes just under a million show as 1.0M and 1.0 MB, not 1000k.
- Large language models count from GPT-1 in June 2018, the earliest fair date, so an ask for 8 years of them isn't called impossible.
