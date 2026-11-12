# The dashboard

[All of the guide](README.md)

`tools/pyrite.py serve` runs it at <http://127.0.0.1:8787>. It only listens on this machine. `tools/pyrite.py open` opens it in your browser, starting it in the background first if it isn't running, and replacing it if it holds the port but has stopped answering. If another program holds the port, it says so and closes nothing. On Windows, double-click `Pyrite.cmd`, which runs `open`. To start it at login, put a shortcut to `.venv\Scripts\pythonw.exe tools\pyrite.py serve` in your Startup folder, with this folder as its working directory, or on Linux use `tools/pyrite/systemd/pyrite-dashboard.service`.

To use another port, such as for a second copy of Pyrite with its own workspace, set it under `[dashboard]` in `search.toml`. `serve`, `open`, `Pyrite.cmd` and the systemd unit all use it, and `serve --port` overrides it for one run:

```toml
[dashboard]
port = 8790
```

A rail down the left names every view: **To do** first, then **Pipeline** with each of its stages under it, **Prospects**, **Closed** and **Industries**, then the **Setup** views, **Profile**, **Facts**, **Sources** and **Settings**. Each shows a count where one helps, such as how many things need you beside To do, and a stage under Pipeline opens the board at its column. To do also has the key numbers on one line beside its name, each with its detail in a tooltip. On a narrow screen the rail becomes a strip of views across the top.

The bar along the top holds one line of status, **Go to**, **Add a posting**, and **Update available** when there is one. The status line says what's running, or when the boards were last read and how many problems there are, such as a failing source or a run that failed. Click it for the whole story and the two run buttons. It names each failing source, up to three, with what went wrong, and **Open Sources** goes to the rest.

**Go to**, a magnifier on a narrower screen, or Ctrl+K (⌘K on a Mac) from anywhere, finds a job, a view, a section of Profile or Settings, or one of the top bar's actions by a few letters of its name, and goes there. Each word you type has to start a word of the name, or of where it is: `firm` finds every firmware job, `cit ind` finds Settings › Cities and industries, and a stage or status such as `applied` finds the jobs at it. Jobs most worth your time come first. With nothing typed, it lists the views, sections and actions. A run that can't start now, such as in the demo, isn't offered.

The dashboard labels its parts in plain words. The code and these docs sometimes use the prospector's name each started with:

| On the dashboard | Also called | What it is |
|---|---|---|
| To do | Sluice | Today's to-do list: what needs you, most urgent first |
| Field report | | The summary each Claude run leaves at the top of the to-do list |
| The stages under Pipeline | Yield | How many jobs are at each stage now, each counted once. Closed has its own count below |
| Pipeline | Claims | Jobs you're working: being tailored, ready, applied and beyond |
| Ready to send | Nuggets | Drafts that passed the assay and are ready to send |
| Prospects | | New postings you haven't judged yet |
| Closed | Tailings | Jobs that are closed out: passed, rejected, ghosted or taken down. Each shows when it closed and the note you gave then, and the tab can be searched and filtered by outcome |
| Sources | Veins | The job boards Pyrite reads, and whether each is working |
| Check boards now | Pan | Reading the boards and checking mail. The command is `pyrite sweep` |
| Fact check | Assay | The checker that decides whether a draft is ready |

The icons follow the same metaphor, reading each stage as a step in a fire assay. Each one appears beside its stage in the rail, at the head of its Pipeline column and at the top of the job panel, and a large faded one fills a view with nothing in it, such as an empty Closed tab. A stage with no jobs greys its icon out.

![The stage icons: a gold pan, an anvil, a streak plate, a furnace, a crucible, a balance, a cupel and a tarnished crystal](images/icon-set.png)

| Icon | Stage | Why |
|---|---|---|
| Gold pan | Prospects | Panned from the boards and not judged yet |
| Anvil | Being tailored | The resume and letter are being forged |
| Streak test | Ready to send | Passed the test that tells gold from fool's gold: pyrite's streak is greenish black |
| Furnace | Waiting to hear | In the fire, out of your hands |
| Crucible | Replied | Something is melting |
| Assay balance | Interviewing | Being weighed. The small gold bead outweighs the big crystal, as it would: gold is nearly four times as dense |
| Cupel and prill | Offer | The bead of real gold left at the end of an assay |
| Tarnished crystal | Closed | Fool's gold, set aside |

The crystal beside the name glints now and then, and throws sparks while a run is going: pyrite's name comes from the Greek for fire, because it sparks when struck against steel. With reduced motion turned on in your system, it holds still. `art/icons/build.py` draws every icon and the pixel wordmark, and its README says how.

The colours mean the same thing everywhere, on the to-do list's tags, on cards and in Prospects:

| Colour | Means | For example |
|---|---|---|
| Brass | Something to act on | The main button, the view you're on, the count of things to do, a key number that needs you |
| Red | It stops you or is urgent | **Blocked**, **Failed assay**, **Possible ghost**, a deadline within two days |
| Orange | Worth acting on soon | **Follow up**, **Possible reply**, **Rework**, **Reposted** once, a deadline within `decide_days` |
| Teal | Information | **New listing**, **Reach out**, **Gaps to answer**, **Your pick**, a preferred city or industry, **Rare near you** |
| Green | Good news | **Send**, **New**, a strong or good fit |
| Grey | For reference | A deadline still weeks away, **May be a repost** |

The page follows your system's light or dark setting.

Two buttons, under the status line at the top, start a run without waiting for the schedule:

- **Check boards now** reads the job boards and checks mail, as the morning sweep does. It uses no AI. [Scheduling and Claude runs](schedule.md) sets both up to run by themselves.
- **Run Claude now** judges the new postings and tailors the best, as the daily run does. It uses your Claude plan, so it asks first.

A third, **Tailor these now**, sits in the **Being tailored** column of the Pipeline board. It has Claude write every draft waiting there, stretch jobs included, without judging new postings and without the daily run's limit, and its result shows under the status line at the top. It uses your Claude plan, so it asks first. A draft that has used up its fix attempts is left alone; **Tailor this one first** on that job gives it another go.

Each runs in the background, shows its progress in the status line while the crystal beside the name throws sparks, and refuses to start while one of its kind is already going. The Claude run and the tailoring batch also refuse to start while the other is going, since both write drafts. The demo starts none of them. A run that stopped because a file under `profile/` changed while it wrote offers **I made this change** in the status line: [When your profile changes during a run](schedule.md#when-your-profile-changes-during-a-run) says what it does.

## The to-do list

**To do** lists what needs you, most urgent first, and each item opens its job. The key numbers beside its name each have a tooltip: **ready to send** counts only drafts whose posting is still up, and its tooltip says how many to check again and how many more came down. The Pipeline board still has every job at its stage.

| Item | When it shows |
|---|---|
| **Finish setup** | Something in your workspace is still the example's or blank, the same findings as `pyrite doctor` |
| **Possible scam** | A posting you haven't sent has a scam's tells, or mail about hiring has them ([Reply detection](mail.md)) |
| **Possible reply** | Mail that looks like a reply to an application. Only your buttons change its status |
| **Act now** | You're interviewing or have an offer, and the date on its **Next step** has come |
| **Follow up** | You applied or heard back, and the date on its **Next step** has come, 7 days after applying unless you changed it (`follow_up_days`) |
| **Send** | A draft passed the assay and its posting is still up. The five best, those closing within two days first |
| **Check again** | A ready draft's files changed after the assay passed it ([The assay](assay.md)) |
| **Closing soon** | A prospect or a job being tailored closes within `decide_days`: tailor it or pass ([Deadlines](applying.md#deadlines-and-what-to-check-before-applying)) |
| **Blocked** | The draft failed the assay. It says when the daily run has stopped retrying it |
| **Posting down** | The posting of a job you sent came down, with when it will count as ghosted |
| **Rework** | A draft you haven't sent was written before you answered one of its gaps |
| **Gone quiet** | Nothing heard `quiet_days` after applying: mark it ghosted, or send one last note |
| **New listing** | The three best postings from the last 7 days that were never reposted |
| **Reach out** | Applications one to three days old with no note to the hiring manager logged, as one item |
| **Gaps to answer** | A requirement has come up as a gap in three applications or more |

Two or more items of one kind share a heading: the tag with how many there are, and what they have in common, said once. Each item under it keeps only its own words, such as when its posting closes. Click the heading to fold the group into one line naming its companies, and again to open it. A group of more than three starts folded, and one you fold or open stays that way in this browser. A group of **Check again** items has **Check all again** beside its heading.

The tag colours follow the table above. The field report from the last Claude run sits at the top, and folds away once you've applied or passed on anything since it was written.

## The job panel

Clicking a job anywhere opens its panel at the side. The header has its stage icon and its number, which the `pyrite` commands take, and the address ends in `#job-` and that number while it's open. The panel runs in the order you'd apply:

- **Before you apply**, when there's something to settle, then a note if the posting came down or may be a ghost job.
- The posting's link, the files to upload, and **Fill Workday form** where it applies ([Applying and after](applying.md)).
- What came back, a frozen copy of what you sent, files changed since the assay passed them, and a draft the run has stopped retrying.
- The status buttons for this stage, such as **Tailor this one first**, **Pass**, **I applied**, **Got a reply**, **Interview**, **Offer**, **Rejected**, **Ghosted**, **Withdraw** or **Reopen**, with an optional note to go with the change.
- The assay's result, then **Rewrite or prepare**: **Refresh resume**, **Interview prep** and **Make fill sheet**, where each applies.
- Tags such as **New** or **Reposted**, then the facts: status, location, pay, track, fit and its reason, and when it was found, posted, reposted, applied and heard back.
- **What Pyrite read into it**: pay against similar roles, rarity and asks nobody could meet ([Pay, rarity and asks nobody could meet](prospects.md#pay-rarity-and-asks-nobody-could-meet)).
- **Moving for it**, for a job outside your area: what its pay is worth after taxes and prices there, against your pay now ([Moving for a job](#moving-for-a-job)).
- **Next step**, a line and a date of your own. The date is what **Follow up** and **Act now** go by, and a rescore keeps a job that has one.
- **Reaching out**, for the note to the hiring manager ([After you apply](applying.md#after-you-apply)).
- **Your notes**, free text kept in the database, saved with **Save notes**. A note keeps the job through a rescore too. A note or next step you haven't saved says **Not saved yet**, and stays in its box if you close the panel and come back, until the page is reloaded.
- **Fit and interview notes**, the job's `notes.md` as tailoring wrote it, with its headings, lists, tables and links drawn as such.
- **Employer**: the research on how the employer works ([How the employer works](applying.md#how-the-employer-works)).
- **Why it scored** and **Why its priority is**, the points behind its place in the list.
- The posting's text, then its **Timeline**: every change of status, run, check and note, newest first.

## Moving for a job

A job outside your area that names its place gets **Moving for it** on its panel: what it would take to live there as you do now, and what its pay range is worth back home. Remote jobs and jobs in your own area don't get it, since they don't ask you to move.

It needs your pay now, set under **Settings › Relocation**, and where you live, which is the metro area or state under **Where you'll work** on the Profile tab. Until your pay is set, the panel says so.

It shows two numbers, each in two views of prices:

- **Break-even pay**: the pay there whose take-home, after the difference in prices, buys what your take-home buys now. Paid that, you'd live as you do; paid more, better.
- **The range in home dollars**: the bottom, middle and top of the posting's range, each taken home there and scaled to prices where you live, with how far each is above or below your take-home now. A posting with no range gets the break-even alone.

The two views of prices:

- **All prices** compares the Bureau of Economic Analysis's all-items price levels, its Regional Price Parities. Housing is about a sixth of that index, as it is for the average household.
- **Renting at market** weighs housing at your share of spending, 30% unless you set another, since moving means paying today's rent or today's house prices there. Everything else is compared at all prices with housing taken out.

If you rent, Renting at market comes first. If you own, All prices does, with a note: a paid-down mortgage or an old low rate can make your housing cost well under the market, and then moving costs more than either view shows.

Only base pay counts, on both sides. A bonus, equity, a signing bonus and the cost of the move itself aren't counted, whatever the posting says.

Taxes are worked out the same way in both places: federal income tax, Social Security and Medicare, the state's income tax, the state's payroll taxes on employees (disability and paid leave insurance, Oregon's transit tax), and the local income taxes that matter most, such as New York City's, Philadelphia's or a Maryland county's. It assumes wages are your only income and you take the standard deduction. Married means a joint return with your pay as the household's only wages. Each table's year is written beside it in `tools/pyrite/taxes.py`, along with what each state leaves out. It's an estimate to decide whether a job is worth a closer look, not tax advice.

A posting's place is read as a city and state. A city that's one of a metro area's principal cities, as the government lists them, gets that metro's prices, so a job in a suburb named in that list finds its metro. Anywhere else gets the state's average, which runs a little high for a small town. When the posting names more than one place, the first in a metro area is used, and the panel says which.

### Local taxes at home

Your local taxes at home can't be told from a metro area, so you name them, under **Local taxes at home** on **Settings › Relocation**. Until you do, a state's statewide one counts, as in Maryland, Indiana and Pennsylvania. The panel has three ways to find yours:

- **Search Pyrite's table** of the city and county income taxes that matter most, by a city, county or state, and **Add** the ones you pay. A job elsewhere comes under the same table, by the city its posting names.
- **Add your own**: a name, a rate, the income it starts above, and whether it's charged on your wages or your state taxable income. A school district's or a transit or housing district's tax, whose boundary no city's name follows, goes here. A tax with two rates is two entries: the second is what it adds over its own threshold.
- **Look up where you live** has Claude search the web for the city, county and district taxes where you live, from the town or county you type. Like employer research, it gets nothing else about you, and every tax it proposes must cite a page the run actually found and read as a rate Pyrite can use. Nothing is saved until you click **Add** beside one, so open its source first. It uses your Claude plan for a few minutes, with the model set under **Models for the smaller jobs**.

In `search.toml` they're two lists under `[relocation]`:

```toml
[relocation]
current_pay = 150000
filing = "single"        # or "married"
housing = "rent"         # or "own"
housing_share = 30       # percent of spending
home_local_taxes = ["nyc"]
own_local_taxes = [
  { name = "Transit district tax", rate = 0.5, base = "wages" },
  { name = "Housing services tax", rate = 1.0, over = 125000, over_married = 200000, base = "taxable" },
]
```

From a terminal, `pyrite relocate --taxes` lists Pyrite's table, `pyrite relocate --taxes ohio` the ones matching a word, and `pyrite relocate --research-taxes "City, ST"` runs the lookup and prints each tax it found as a line to paste.

### The command and the price levels

`pyrite relocate <id>` prints the same comparison for a job, and `pyrite relocate --where "City, ST" --pay "$165k-$215k"` for any place and pay.

The price levels don't ship with Pyrite. The first comparison downloads them from BEA, and each metro area's principal cities from the Census Bureau, about 200 KB in all, and keeps them in the workspace's `data/prices/rpp.json`. Without a network the first time, the panel says it couldn't get them, and Pyrite tries again within the hour. BEA publishes a new year each December, so a copy over 60 days old is looked for anew, and kept if the download fails. `pyrite relocate --refresh-prices` downloads them again now.

## Keys

| Key | Where | Does |
|---|---|---|
| **Ctrl+K**, or **⌘K** on a Mac | Anywhere | Opens **Go to**, or closes it. In it, **↑** and **↓** choose and **Enter** goes |
| **/** | Anywhere but a text box | Opens Prospects with its search box ready to type in |
| **J** and **K** | To do, the Pipeline board, Prospects or Closed, with no panel open | Moves down and up the list. **Enter** opens the one you're on. A folded group's items are skipped |
| **J** and **K** | A job's panel | The next and previous job in the list you opened it from |
| **T** and **P** | The panel of a job nothing has been written for | Tailor this one first, or pass, then open the next |
| **Esc** | A panel, or the status line's details | Closes it |
| **Enter** | The box for a confirmation code | Confirms |

## Settings

**Settings** is how Pyrite runs. It has a menu of its own under its name, and the address keeps the section you're on, as `#settings/mail`:

| Section | What it sets | In `search.toml` |
|---|---|---|
| **Claude** | Which model judges postings and writes drafts, and how hard it thinks. The models for the smaller jobs: reading mail, industry outlooks, skill ages, employer research and local tax research | `[claude]` `model` and `effort`; `model` under `[inbox]`, `[market]`, `[skills]`, `[culture]` and `[relocation]` |
| **Mail** | Whether replies are read over IMAP or through the Gmail connector, and how many days back | `[inbox]` `source` and `lookback_days` |
| **Daily run** | When the pan and the daily run start, on Windows. How many postings are judged and resumes written each morning, how many tries a draft gets, and whether a cover letter is written | Task Scheduler, for when. `[run]` `triage_per_day`, `tailor_per_day`, `fix_attempts` and `cover_letters` |
| **Dashboard** | When the to-do list reminds you to follow up, calls an application ghosted or a deadline close, whether it reminds you to reach out, and whether it asks GitHub for updates | `[run]` `follow_up_days`, `quiet_days` and `decide_days`; `[dashboard]` `reach_out` and `check_updates` |
| **Relocation** | Your pay now, filing status, whether you rent or own, your share of spending on housing, and your local taxes at home, for [Moving for a job](#moving-for-a-job) | `[relocation]` `current_pay`, `filing`, `housing`, `housing_share`, `home_local_taxes` and `own_local_taxes` |
| **Cities and industries** | The places and industries to see first. [Preferred cities and industries](prospects.md#preferred-cities-and-industries) covers it | `[promote]` |

Claude and Mail open with a **Connection** panel: whether Claude Code is on this computer and signed in, and where replies are read from, whether the last read worked and when. **Check again** asks Claude Code afresh, which takes a second or two.

Daily run opens with **When it runs**, which sets the pan and the daily run up in Windows Task Scheduler, moves them to another time or removes them, each after you confirm. [Setting them up](schedule.md#setting-them-up) says what it makes and what it leaves alone.

Each panel has its own **Save**, which writes only the settings you changed in that panel. A setting is one key in `search.toml`: the save sets that key where it is, or adds it to its table, and every other line and comment stays as it was. Emptying a box takes the key out, so Pyrite's default applies again, and the box names that default. The file from before each save is kept in the Profile tab's History, where **Put back** restores it.

The model and effort apply to judging, tailoring, Refresh resume and Interview prep. Left empty, Claude Code uses its own default for each, and your own Claude Code settings don't decide it, since a run reads only the workspace's. A model is a name or alias Claude Code knows, such as `opus`, `sonnet` or `claude-sonnet-5-5`.

Nothing in Settings can let drafts say more. The patterns under `[guard]`, the filters, the port and the names under `allowed_hosts` aren't there, because the dashboard has no login. The demo can't save settings.

## Updating Pyrite

Once an hour while the page is open, the dashboard fetches GitHub's `main` into Pyrite's code folder and compares it with the copy you're running. When GitHub's is ahead, an **Update available** button appears at the top, beside **Add a posting**. It lists what the new commits say, leaving out merges, and **Update and restart** moves the code forward to match, runs `pip install -r tools/requirements.txt` with the Python running Pyrite if that file changed, and restarts the dashboard so it runs the new code. The page reloads on its own once the new one answers. Your workspace isn't touched.

It only ever moves forward, so it never merges or throws work away. A code folder on another branch, with every commit of that branch already in GitHub's `main`, such as the branch of a pull request that has since been merged, gets **Switch to main and update** instead: it switches the folder to `main` first and keeps the branch. It does nothing when the code folder has edits of your own to files git tracks, or commits GitHub's `main` doesn't. It says which, and the git commands to run in the folder, and **Check again** reads the folder again once you have. It also waits while a pan, Claude run or tailoring batch is going, since those run the code being replaced. A pan the schedule started counts too. In the demo it says how to update instead. A code folder cloned from an `http://` or `git://` address is never checked or updated from here, since anyone on the network could swap in code of their own: point it at an `https://` or SSH address with `git remote set-url`.

A dashboard started with `pyrite serve` in a terminal stops there and comes back in the background, as `pyrite open` would start it. To never ask GitHub, set this, and update with `git pull` when you choose:

```toml
[dashboard]
check_updates = false
```
