### Changed

- The dashboard opens on what it showed last time, saying how old that is, while it works out the latest. Before, a page loaded after a restart stayed empty for several seconds.
- The dashboard starts working out the page as soon as it starts, before the browser asks, and a page that asks while that's going shares it rather than starting another.
- Loading the page is faster: preferred-industry matching checks each posting in one pass, and grouping the gaps in your notes no longer compares every gap with every other.
