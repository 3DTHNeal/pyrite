# Workday: field-by-field copy

Every Workday careers site asks the same pages in the same order. This file holds the answer for each field, in that order, so an application can be filled from here instead of from whatever Workday parses out of the PDF. Everything below comes from `facts.md`. If a fact changes, change it there first.

`pyrite fill <job>` copies this sheet into the job's folder as `fill-sheet.md`, with each role's description replaced by the tailored text from that job's `resume.md`. For that it needs each role below to keep its `Job title` and `Company` rows and one fenced text block.

## How to use this

- **Don't let Workday parse the resume.** On the "My Experience" page, choose "Fill out manually", then attach the PDF under "Resume/CV". If a site forces the parse, accept it and overwrite every field it filled from the blocks below.
- **Alex signs in, reviews each page, and clicks Submit.** Nobody and nothing else submits.
- **Dates** are typed as `MM/YYYY` into Workday's month and year boxes.

## Page 1: My Information

| Field | Value |
|---|---|
| How did you hear about us | *Ask Alex per application.* Usually "Company careers site" or "LinkedIn"; if someone referred them, pick "Employee referral" and name them |
| Have you previously worked for us | No |
| Country | United States of America |
| Legal name | Alex Rivera |
| Address | *Street and ZIP not on record; Alex fills these.* City: Madison. State: Wisconsin |
| Email | alex.rivera@example.com |
| Phone device type | Mobile |
| Phone number | 5550100142 |

## Page 2: My Experience

### Work experience 1

| Field | Value |
|---|---|
| Job title | Principal Firmware Engineer |
| Company | Northbridge Robotics |
| Location | Madison, WI |
| I currently work here | No |
| From | 01/2023 |
| To | 10/2026 |

Role description:

```text
Built the firmware team's AI-assisted workflow and the simulation it was measured against.
• Built an internal coding-agent workflow with Claude Code, reviewed by automated gates, that delivered 180 tasks.
• Replaced a hand-tuned PID loop with a calibrated model, cutting settling time about 35% on the test rig.
```

### Work experience 2

| Field | Value |
|---|---|
| Job title | Firmware Engineering Manager |
| Company | Northbridge Robotics |
| Location | Madison, WI |
| I currently work here | No |
| From | 03/2020 |
| To | 01/2023 |

Role description:

```text
Managed a team of 7 firmware and test engineers. Software lead on 3 robot launches.
```

### Work experience 3

| Field | Value |
|---|---|
| Job title | Senior Firmware Engineer |
| Company | Northbridge Robotics |
| Location | Madison, WI |
| I currently work here | No |
| From | 06/2017 |
| To | 03/2020 |

Role description:

```text
Wrote motor-control firmware in C++ for a fleet of 1,400 warehouse robots.
```

### Work experience 4

| Field | Value |
|---|---|
| Job title | Embedded Software Engineer |
| Company | Lakeshore Instruments |
| Location | Milwaukee, WI |
| I currently work here | No |
| From | 08/2012 |
| To | 06/2017 |

Role description:

```text
Wrote embedded software for industrial instruments.
```

### Education 1

| Field | Value |
|---|---|
| School or university | University of Wisconsin–Madison |
| Degree | Bachelor of Science |
| Field of study | Computer Engineering |
| To | 2012 |

### Languages

English, Fluent (native).

### Certifications

| Certification | Issuer | Date |
|---|---|---|
| Certified ScrumMaster | Scrum Alliance | *not on record; ask Alex* |

### Skills

Workday's skill box only accepts its own entries. Search each and add it if it exists; skip the ones it doesn't have.

Firmware, C++, Python, Linux, Machine Learning, Simulation, Scrum, Engineering Management

### Resume/CV

Attach the tailored PDF from `applications/<job>/`. One file only.

### Websites

| Field | Value |
|---|---|
| Website | https://www.linkedin.com/in/alex-rivera-example |

## Page 3: Application questions

| Question | Answer |
|---|---|
| Are you 18 or older | Yes |
| Legally authorized to work in the United States | *Ask Alex once; record here* |
| Willing to relocate | No. Madison area or remote |
| Salary expectations | *Ask Alex per application.* Blank if optional, a tight range inside the posted band if a range is allowed, a single number only if forced |
| Years of relevant experience | 14 |

## Page 4: Voluntary disclosures

Alex fills these. They're optional and don't affect the application.

## Page 5: Review and Submit

Alex reads the review page and clicks Submit. Then click **I applied** on the dashboard.
