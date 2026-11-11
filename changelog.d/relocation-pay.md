### Added

- **Moving for it** on the panel of a job outside your area: the pay there that would let you live as you do now, after taxes and local prices, and what the bottom, middle and top of its range are worth back home. Two views of prices: all items, and renting at market with housing at your share of spending. Base pay only: a bonus or equity isn't counted.
- **Settings › Relocation** sets your pay now, filing status, whether you rent or own, and your share of spending on housing, under `[relocation]` in `search.toml`. Home is the metro or state under `[market]`.
- `pyrite relocate <id>` prints the same comparison for a job, `pyrite relocate --where "City, ST" --pay "$165k-$215k"` for any place and pay, and `pyrite relocate --taxes` the local income taxes it knows.
- BEA's Regional Price Parities for every metro area and state ship with Pyrite, with `tools/refresh_prices.py` to rebuild them when BEA publishes a new year. A tax model for every state, with the year of each table beside it, is in `tools/pyrite/taxes.py`.
- The demo has a job in another state with a pay range, to show **Moving for it**.
