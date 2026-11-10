### Added

- For tools built on the assay package: `numbers.number_findings` gives the number check's verdict as data, each unsupported figure with its kind, value and place in the text, and `numbers.quantities` reads every number a text states. A `Policy` says how closely the evidence must state a figure. The default is unchanged. `numbers.MEASURED` is for evidence that states its unit once and rounds as it pleases, such as a filing's table in thousands. What a Pyrite draft passes or fails is the same as before, and a test compares the two line by line.
