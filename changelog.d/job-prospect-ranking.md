### Added

- **Turned you down before**: another opening at an employer that turned you down before any interview, in the last `turned_down_days` (180), loses `turned_down_penalty` (10) priority for each such rejection, two at most, and shows the tag. A rejection after an interview or a ghosted application doesn't count.
- The daily run's triage hears what came back from your recent applications: the ones turned down before an interview and the gaps their notes named, and the ones that led to a reply or an interview. A posting whose stated minimum repeats a gap that came before a rejection gets a lower verdict, with the gap named. `pyrite queue --json` carries the same as `what_came_back`.

### Changed

- A job outside your area, kept only for an industry marked `anywhere`, now loses `elsewhere_penalty` (30) priority until triage calls it a strong fit, so it ranks below local and remote roles unless it's close to perfect. Triage is told it's outside your area and gives such a job strong or skip. A job you added yourself never loses it.
