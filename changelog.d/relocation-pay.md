### Added

- **Moving for it** on the panel of a job outside your area: the pay there that would let you live as you do now, after taxes and local prices, and what the bottom, middle and top of its range are worth back home. Two views of prices: all items, and renting at market with housing at your share of spending. Base pay only: a bonus or equity isn't counted.
- **Settings › Relocation** sets your pay now, filing status, whether you rent or own, and your share of spending on housing, under `[relocation]` in `search.toml`. Home is the metro or state under `[market]`.
- `pyrite relocate <id>` prints the same comparison for a job, and `pyrite relocate --where "City, ST" --pay "$165k-$215k"` for any place and pay.
- **Local taxes at home** on Settings › Relocation: search Pyrite's table of city and county income taxes, add your own as a rate over a threshold (for a school or district tax no city name tells apart), or have Claude look up the ones where you live, each with a source, and add the ones you check. `pyrite relocate --taxes` and `--research-taxes "City, ST"` do the same from a terminal.
- The first comparison downloads BEA's Regional Price Parities and the Census Bureau's list of each metro area's principal cities into the workspace, and looks for a newer year once they're 60 days old. `pyrite relocate --refresh-prices` downloads them again now. Federal, state, payroll and local taxes are in `tools/pyrite/taxes.py`, with the year of each table beside it.
- The demo has a job in another state with a pay range, to show **Moving for it**.
