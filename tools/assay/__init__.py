"""The assay: deterministic checks that a piece of generated text claims nothing its sources don't support.

It knows nothing about any one use of it. Every function here takes text and the evidence to judge it by, and
returns what it found. It reads no files of its own choosing, starts no programs, opens no network connection and calls
no model, so the same input always gets the same verdict and there is nothing in it to persuade. A test holds it to
that: nothing here may import from outside this package except a short list of standard-library modules.

- `text`: reading text as a reader sees it, so look-alike letters, invisible characters and emphasis can't hide a word.
- `factbank`: the sections of a hand-written fact bank, and which parts of it approve nothing.
- `numbers`: numbers keep their value and scale, and multiples, fractions and spelled-out numbers count as numbers.
  A policy says how closely the evidence must state a figure: exactly, or as a filing's table does.
- `findings`: what a check found as data, with its place in the text, for a caller that stores or shows results.
- `terms`: specialist terms the sources never use, and terms borrowed from a reference text that isn't evidence.
- `names`: confidential names, blocked however they're split, joined or pluralized.
- `claims`: unsupported claims, and when a sentence names one only to deny it.
- `links`: web addresses, domains and emails the sources don't write.
- `seal`: hashes that tie a verdict to the exact text, sources and rules it judged, and to this version of the checker.

A tool builds its own gate from these, adding the rules particular to what it writes.
"""

# The checker's own version, apart from any tool's built on it. The minor number goes up whenever a verdict could change
# under some policy, and the major one when a caller would have to change too, so a seal that records it says which rules
# gave a pass. 1.0 was the package with findings and policies, and 1.1 adds what a policy sets aside as not measured.
# 1.2 sets aside a day with no year, a reference to a place in a document and two more kinds of identifier, and lets a
# policy read scale widely: after a currency code, in the plural, and once for a range.
__version__ = "1.2.0"
