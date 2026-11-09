# The dashboard

[All of the guide](README.md)

`tools/pyrite.py serve` runs it at <http://127.0.0.1:8787>. It only listens on this machine. `tools/pyrite.py open` opens it in your browser, starting it in the background first if it isn't running, and replacing it if it holds the port but has stopped answering. If another program holds the port, it says so and closes nothing. On Windows, double-click `Pyrite.cmd`, which runs `open`. To start it at login, put a shortcut to `.venv\Scripts\pythonw.exe tools\pyrite.py serve` in your Startup folder, with this folder as its working directory, or on Linux use `tools/pyrite/systemd/pyrite-dashboard.service`.

To use another port, such as for a second copy of Pyrite with its own workspace, set it under `[dashboard]` in `search.toml`. `serve`, `open`, `Pyrite.cmd` and the systemd unit all use it, and `serve --port` overrides it for one run:

```toml
[dashboard]
port = 8790
```

A rail down the left names every view: **To do** first, then **Pipeline** with each of its stages under it, **Prospects**, **Closed** and **Industries**, then the **Setup** views, **Profile**, **Facts**, **Sources** and **Settings**. Each shows a count where one helps, such as how many things need you beside To do, and a stage under Pipeline opens the board at its column. To do also has the key numbers on one line beside its name, each with its detail in a tooltip. On a narrow screen the rail becomes a strip of views across the top.

The bar along the top holds one line of status, **Add a posting**, and **Update available** when there is one. The status line says what's running, or when the boards were last read and how many problems there are, such as a failing source or a run that failed. Click it for the whole story and the two run buttons.

The dashboard labels its parts in plain words. The code and these docs sometimes use the prospector's name each started with:

| On the dashboard | Also called | What it is |
|---|---|---|
| To do | Sluice | Today's to-do list: what needs you, most urgent first |
| Field report | | The summary each Claude run leaves at the top of the to-do list |
| The stages under Pipeline | Yield | How many jobs are at each stage now, each counted once. Closed has its own count below |
| Pipeline | Claims | Jobs you're working: being tailored, ready, applied and beyond |
| Ready to send | Nuggets | Drafts that passed the assay and are ready to send |
| Prospects | | New postings you haven't judged yet |
| Closed | Tailings | Jobs that are closed out: passed, rejected, ghosted or taken down |
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
| Orange | Worth acting on soon | **Follow up**, **Possible reply**, **Reposted** once, a deadline within `decide_days` |
| Teal | Information | **New listing**, **Reach out**, **Your pick**, a preferred city or industry, **Rare near you** |
| Green | Good news | **Send**, **New**, a strong or good fit |
| Grey | For reference | A deadline still weeks away, **May be a repost** |

The page follows your system's light or dark setting.

Two buttons, under the status line at the top, start a run without waiting for the schedule:

- **Check boards now** reads the job boards and checks mail, as the morning sweep does. It uses no AI. [Scheduling and Claude runs](schedule.md) sets both up to run by themselves.
- **Run Claude now** judges the new postings and tailors the best, as the daily run does. It uses your Claude plan, so it asks first.

A third, **Tailor these now**, sits in the **Being tailored** column of the Pipeline board. It has Claude write every draft waiting there, stretch jobs included, without judging new postings and without the daily run's limit, and its result shows under the status line at the top. It uses your Claude plan, so it asks first. A draft that has used up its fix attempts is left alone; **Tailor this one first** on that job gives it another go.

Each runs in the background, shows its progress in the status line while the crystal beside the name throws sparks, and refuses to start while one of its kind is already going. The Claude run and the tailoring batch also refuse to start while the other is going, since both write drafts. The demo starts none of them.

## Updating Pyrite

Once an hour while the page is open, the dashboard fetches GitHub's `main` into Pyrite's code folder and compares it with the copy you're running. When GitHub's is ahead, an **Update available** button appears at the top, beside **Add a posting**. It lists what the new commits say, and **Update and restart** moves the code forward to match, runs `pip install -r tools/requirements.txt` with the Python running Pyrite if that file changed, and restarts the dashboard so it runs the new code. The page reloads on its own once the new one answers. Your workspace isn't touched.

It only ever fast-forwards, so it never merges or throws work away. It says why and does nothing when the code folder is on a branch other than `main`, has edits of your own to files git tracks, or has commits GitHub's `main` doesn't: run `git pull` there yourself in those cases. It also waits while a pan, Claude run or tailoring batch is going, since those run the code being replaced. A pan the schedule started counts too. In the demo it says how to update instead. A code folder cloned from an `http://` or `git://` address is never checked or updated from here, since anyone on the network could swap in code of their own: point it at an `https://` or SSH address with `git remote set-url`.

A dashboard started with `pyrite serve` in a terminal stops there and comes back in the background, as `pyrite open` would start it. To never ask GitHub, set this, and update with `git pull` when you choose:

```toml
[dashboard]
check_updates = false
```
