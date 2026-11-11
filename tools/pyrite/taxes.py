"""What a year's wages leave after tax, in any US state, for comparing a job in one place with pay in another.

A small, honest model, not tax advice. What it assumes:

- Wages are the only income, and the standard deduction is taken. No itemizing, no credits for children or dependents,
  no pre-tax 401(k) or health premiums, which would lower every tax below by about the same share wherever you live.
- "single" is a single filer. "married" is a joint return on which the candidate's wages are the household's only
  wages, so two earners would pay somewhat more than this says.
- Federal income tax, Social Security and Medicare (FICA, with the extra 0.9% Medicare), the state's income tax, the
  state's mandatory payroll taxes on employees (disability and paid leave insurance, transit taxes), and a short table
  of the local income taxes that matter most. Local taxes not in LOCAL are left out, and the table's notes say so.
- Each state's brackets, standard deduction, personal exemption and personal credits, and the phase-outs and
  recaptures that change the answer by more than a few hundred dollars at pay from about $50k to $500k. What's left
  out is said beside the state.

Every table says its tax year. The federal ones are 2026 (IRS Rev. Proc. 2025-32, after the 2025 tax law). The state
ones are as of January 1, 2026, from each state's revenue department as compiled by the Tax Foundation ("State
Individual Income Tax Rates and Brackets, 2026"); a state that hadn't published its 2026 inflation adjustment by then
is marked 2025, which is what it is. Payroll and local rates carry their own years. When a year turns, change the
tables here and the years beside them, and the tests in test_relocate.py say what moved.
"""
import re
from dataclasses import dataclass, field
from typing import Any

INF = float("inf")
FILINGS = ("single", "married")
Brackets = tuple[tuple[float, float], ...]  # Each (the income it starts above, the rate on income past that), in order.


def bracket_tax(income: float, brackets: Brackets) -> float:
    """The tax on `income` by brackets, each a rate on what's past its start, up to the next one's start."""
    tax = 0.0
    for (start, rate), (top, _next_rate) in zip(brackets, [*brackets[1:], (INF, 0.0)], strict=True):
        if income > start:
            tax += (min(income, top) - start) * rate
    return tax


def _by_filing(pair: tuple[Any, Any], filing: str) -> Any:
    return pair[1] if filing == "married" else pair[0]


def _phased(amount: float, income: float, span: tuple[float, float] | None) -> float:
    """`amount`, reduced in a straight line to nothing as income goes from the span's start to its end. A span whose
    start and end are equal is a cliff: all of it until then, none after."""
    if not span:
        return amount
    start, end = span
    if income <= start:
        return amount
    if income >= end:
        return 0.0
    return amount * (end - income) / (end - start)


# Federal, 2026: IRS Rev. Proc. 2025-32.
FEDERAL_YEAR = 2026
FEDERAL_DEDUCTION = (16_100, 32_200)
FEDERAL_BRACKETS: tuple[Brackets, Brackets] = (
    ((0, .10), (12_400, .12), (50_400, .22), (105_700, .24), (201_775, .32), (256_225, .35), (640_600, .37)),
    ((0, .10), (24_800, .12), (100_800, .22), (211_400, .24), (403_550, .32), (512_450, .35), (768_700, .37)),
)
# FICA, 2026: Social Security Administration and IRS. Medicare's extra 0.9% starts at these wages, which aren't indexed.
SOCIAL_SECURITY_RATE, SOCIAL_SECURITY_BASE = .062, 184_500
MEDICARE_RATE, EXTRA_MEDICARE_RATE = .0145, .009
EXTRA_MEDICARE_FROM = (200_000, 250_000)


def federal_income_tax(wages: float, filing: str = "single") -> float:
    return bracket_tax(max(0.0, wages - _by_filing(FEDERAL_DEDUCTION, filing)), _by_filing(FEDERAL_BRACKETS, filing))


def fica(wages: float, filing: str = "single") -> float:
    extra = max(0.0, wages - _by_filing(EXTRA_MEDICARE_FROM, filing)) * EXTRA_MEDICARE_RATE
    return min(wages, SOCIAL_SECURITY_BASE) * SOCIAL_SECURITY_RATE + wages * MEDICARE_RATE + extra


@dataclass(frozen=True)
class StateTax:
    """One state's income tax on wages. Pairs are (single, married filing jointly)."""
    year: int
    single: Brackets = ()
    married: Brackets | None = None  # None: the same brackets as single.
    deduction: tuple[float, float] = (0, 0)  # The standard deduction.
    exemption: tuple[float, float] = (0, 0)  # The personal exemption, a deduction.
    credit: tuple[float, float] = (0, 0)  # A personal credit, taken off the tax.
    deduction_phaseout: tuple[tuple[float, float], tuple[float, float]] | None = None  # Income span over which it goes.
    exemption_phaseout: tuple[tuple[float, float], tuple[float, float]] | None = None  # The exemption and the credit.
    federal_deduction: tuple[float, float] = (0, 0)  # Federal income tax deductible from state income, up to these.
    federal_phaseout: tuple[tuple[float, float], tuple[float, float]] | None = None
    floor_share: tuple[float, float] | None = None  # (income over which, share): the tax is at least this share of it.
    note: str = ""

    def brackets(self, filing: str) -> Brackets:
        return self.married if filing == "married" and self.married is not None else self.single


# No tax on wages. New Hampshire's interest and dividends tax ended with 2024, and Washington's tax is on capital gains.
NONE = StateTax(2026)
STATES: dict[str, StateTax] = {
    "AK": NONE, "FL": NONE, "NV": NONE, "NH": NONE, "SD": NONE, "TN": NONE, "TX": NONE, "WA": NONE, "WY": NONE,
    "AL": StateTax(2026, ((0, .02), (500, .04), (3_000, .05)), ((0, .02), (1_000, .04), (6_000, .05)),
                   deduction=(2_500, 5_000), exemption=(1_500, 3_000), federal_deduction=(INF, INF),
                   note="Federal income tax is deductible. The standard deduction is the floor it slides to above about $35k."),
    "AZ": StateTax(2026, ((0, .025),), deduction=(8_350, 16_700)),
    "AR": StateTax(2025, ((0, .02), (4_600, .039)), deduction=(2_470, 4_940), credit=(29, 58),
                   note="The table for income over $92,300. Below that a lower table applies, which this doesn't model."),
    "CA": StateTax(2025, ((0, .01), (11_079, .02), (26_264, .04), (41_452, .06), (57_542, .08), (72_724, .093),
                          (371_479, .103), (445_771, .113), (742_953, .123), (1_000_000, .133)),
                   ((0, .01), (22_158, .02), (52_528, .04), (82_904, .06), (115_084, .08), (145_448, .093),
                    (742_958, .103), (891_542, .113), (1_000_000, .123), (1_485_906, .133)),
                   deduction=(5_540, 11_080), credit=(153, 306),
                   exemption_phaseout=((252_203, 315_953), (504_411, 567_911)),
                   note="Brackets and deduction are 2025's, the latest indexed. 13.3% includes the 1% over $1M."),
    "CO": StateTax(2026, ((0, .044),), deduction=(16_100, 32_200)),
    "CT": StateTax(2026, ((0, .02), (10_000, .045), (50_000, .055), (100_000, .06), (200_000, .065), (250_000, .069),
                          (500_000, .0699)),
                   ((0, .02), (20_000, .045), (100_000, .055), (200_000, .06), (400_000, .065), (500_000, .069),
                    (1_000_000, .0699)),
                   exemption=(15_000, 24_000), exemption_phaseout=((30_000, 45_000), (48_000, 72_000)),
                   note="Includes the phase-out of the 2% bracket and the benefit recapture, approximately."),
    "DE": StateTax(2026, ((2_000, .022), (5_000, .039), (10_000, .048), (20_000, .052), (25_000, .0555), (60_000, .066)),
                   deduction=(3_250, 6_500), credit=(110, 220)),
    "DC": StateTax(2026, ((0, .04), (10_000, .06), (40_000, .065), (60_000, .085), (250_000, .0925), (500_000, .0975),
                          (1_000_000, .1075)), deduction=(16_100, 32_200)),
    "GA": StateTax(2026, ((0, .0519),), deduction=(12_000, 24_000)),
    "HI": StateTax(2026, ((0, .014), (9_600, .032), (14_400, .055), (19_200, .064), (24_000, .068), (36_000, .072),
                          (48_000, .076), (125_000, .079), (175_000, .0825), (225_000, .09), (275_000, .10), (325_000, .11)),
                   ((0, .014), (19_200, .032), (28_800, .055), (38_400, .064), (48_000, .068), (72_000, .072),
                    (96_000, .076), (250_000, .079), (350_000, .0825), (450_000, .09), (550_000, .10), (650_000, .11)),
                   deduction=(4_400, 8_800), exemption=(1_144, 2_288),
                   note="Hawaii's temporary disability insurance, under $8 a week, is left out."),
    "ID": StateTax(2025, ((4_811, .053),), ((9_622, .053),), deduction=(16_100, 32_200)),
    "IL": StateTax(2026, ((0, .0495),), exemption=(2_925, 5_850), exemption_phaseout=((250_000, 250_000), (500_000, 500_000))),
    "IN": StateTax(2026, ((0, .0295),), exemption=(1_000, 2_000)),
    "IA": StateTax(2026, ((0, .038),), deduction=(16_100, 32_200), credit=(40, 80)),
    "KS": StateTax(2026, ((0, .052), (23_000, .0558)), ((0, .052), (46_000, .0558)), deduction=(3_605, 8_240),
                   exemption=(9_160, 18_320)),
    "KY": StateTax(2026, ((0, .035),), deduction=(3_360, 3_360)),
    "LA": StateTax(2026, ((0, .03),), deduction=(12_875, 25_750)),
    "ME": StateTax(2026, ((0, .058), (27_399, .0675), (64_849, .0715)), ((0, .058), (54_849, .0675), (129_749, .0715)),
                   deduction=(8_350, 16_700), exemption=(5_300, 10_600),
                   deduction_phaseout=((100_000, 175_000), (200_050, 350_050)),
                   note="The personal exemption's phase-out, from about $333k, is left out."),
    "MD": StateTax(2026, ((0, .02), (1_000, .03), (2_000, .04), (3_000, .0475), (100_000, .05), (125_000, .0525),
                          (150_000, .055), (250_000, .0575), (500_000, .0625), (1_000_000, .065)),
                   ((0, .02), (1_000, .03), (2_000, .04), (3_000, .0475), (150_000, .05), (175_000, .0525),
                    (225_000, .055), (300_000, .0575), (600_000, .0625), (1_200_000, .065)),
                   deduction=(3_350, 6_700), exemption=(3_200, 6_400),
                   exemption_phaseout=((100_000, 150_000), (150_000, 200_000)),
                   note="Every Maryland county also taxes income: see LOCAL."),
    "MA": StateTax(2025, ((0, .05), (1_083_150, .09)), exemption=(4_400, 8_800)),
    "MI": StateTax(2026, ((0, .0425),), exemption=(5_900, 11_800)),
    "MN": StateTax(2026, ((0, .0535), (33_310, .068), (109_430, .0785), (203_150, .0985)),
                   ((0, .0535), (48_700, .068), (193_480, .0785), (337_930, .0985)), deduction=(15_300, 30_600),
                   note="The standard deduction's reduction over $244,400 is left out."),
    "MS": StateTax(2026, ((10_000, .04),), deduction=(2_300, 4_600), exemption=(6_000, 12_000)),
    "MO": StateTax(2026, ((1_348, .02), (2_696, .025), (4_044, .03), (5_392, .035), (6_740, .04), (8_088, .045), (9_436, .047)),
                   deduction=(16_100, 32_200),
                   note="The partial deduction for federal tax, which ends at $125k of income, is left out."),
    "MT": StateTax(2026, ((0, .047), (47_500, .0565)), ((0, .047), (95_000, .0565)), deduction=(16_100, 32_200)),
    "NE": StateTax(2026, ((0, .0246), (4_130, .0351), (24_760, .0455)), ((0, .0246), (8_250, .0351), (49_530, .0455)),
                   deduction=(8_850, 17_700), credit=(176, 352)),
    "NJ": StateTax(2026, ((0, .014), (20_000, .0175), (35_000, .035), (40_000, .05525), (75_000, .0637), (500_000, .0897),
                          (1_000_000, .1075)),
                   ((0, .014), (20_000, .0175), (50_000, .0245), (70_000, .035), (80_000, .05525), (150_000, .0637),
                    (500_000, .0897), (1_000_000, .1075)), exemption=(1_000, 2_000)),
    "NM": StateTax(2026, ((0, .015), (5_500, .032), (16_500, .043), (33_500, .047), (66_500, .049), (210_000, .059)),
                   ((0, .015), (8_000, .032), (25_000, .043), (50_000, .047), (100_000, .049), (315_000, .059)),
                   deduction=(16_100, 32_200)),
    "NY": StateTax(2026, ((0, .039), (8_500, .044), (11_700, .0515), (13_900, .054), (80_650, .059), (215_400, .0685),
                          (1_077_550, .0965), (5_000_000, .103), (25_000_000, .109)),
                   ((0, .039), (17_150, .044), (23_600, .0515), (27_900, .054), (161_550, .059), (323_200, .0685),
                    (2_155_350, .0965), (5_000_000, .103), (25_000_000, .109)), deduction=(8_000, 16_050),
                   note="Includes the recapture that taxes more of a high income at its top rate, approximately."),
    "NC": StateTax(2026, ((0, .0399),), deduction=(12_750, 25_500)),
    "ND": StateTax(2025, ((48_475, .0195), (244_825, .025)), ((80_975, .0195), (298_075, .025)), deduction=(16_100, 32_200)),
    "OH": StateTax(2026, ((26_050, .0275),), exemption=(1_900, 3_800),
                   note="The exemption is the one for income from $80k to $500k."),
    "OK": StateTax(2026, ((3_750, .025), (4_900, .035), (7_200, .045)), ((7_500, .025), (9_800, .035), (14_400, .045)),
                   deduction=(6_350, 12_700), exemption=(1_000, 2_000)),
    "OR": StateTax(2026, ((0, .0475), (4_550, .0675), (11_400, .0875), (125_000, .099)),
                   ((0, .0475), (9_100, .0675), (22_800, .0875), (250_000, .099)),
                   deduction=(2_910, 5_820), credit=(256, 512), exemption_phaseout=((100_000, 100_000), (200_000, 200_000)),
                   federal_deduction=(8_500, 8_500), federal_phaseout=((125_000, 145_000), (250_000, 290_000)),
                   note="Federal tax is deductible up to $8,500 (the 2025 limit), less above $125k of income."),
    "PA": StateTax(2026, ((0, .0307),), note="Most towns and school districts also tax wages: see LOCAL."),
    "RI": StateTax(2026, ((0, .0375), (82_050, .0475), (186_450, .0599)), deduction=(11_200, 22_400),
                   exemption=(5_250, 10_500), deduction_phaseout=((261_000, 290_800), (261_000, 290_800)),
                   exemption_phaseout=((261_000, 290_800), (261_000, 290_800))),
    "SC": StateTax(2026, ((0, 0.0), (3_640, .03), (18_230, .06)), deduction=(8_350, 16_700)),
    "UT": StateTax(2026, ((0, .045),), credit=(966, 1_932), exemption_phaseout=((18_213, 92_520), (36_426, 185_042)),
                   note="The standard deduction is a 6% credit that fades out from $18,213 (2025's start)."),
    "VT": StateTax(2025, ((0, .0335), (49_400, .066), (119_700, .076), (249_700, .0875)),
                   ((0, .0335), (82_500, .066), (199_450, .076), (304_000, .0875)),
                   deduction=(7_650, 15_300), exemption=(5_300, 10_600), floor_share=(150_000, .03)),
    "VA": StateTax(2026, ((0, .02), (3_000, .03), (5_000, .05), (17_000, .0575)), deduction=(8_750, 17_500),
                   exemption=(930, 1_860)),
    "WV": StateTax(2026, ((0, .0222), (10_000, .0296), (25_000, .0333), (40_000, .0444), (60_000, .0482)),
                   exemption=(2_000, 4_000)),
    "WI": StateTax(2026, ((0, .035), (15_110, .044), (51_950, .053), (332_720, .0765)),
                   ((0, .035), (20_150, .044), (69_260, .053), (443_630, .0765)),
                   deduction=(13_960, 25_840), exemption=(700, 1_400),
                   deduction_phaseout=((20_119, 136_453), (29_039, 159_690))),
}


@dataclass(frozen=True)
class Payroll:
    """A state's tax on employees' wages besides income tax. `cap` is the most wages it's charged on."""
    name: str
    rate: float
    year: int
    cap: float = INF
    flat: float = 0.0  # A fixed yearly amount on top.


# Each state's mandatory employee payroll taxes. Only the employee's share: what an employer pays isn't take-home.
PAYROLL: dict[str, tuple[Payroll, ...]] = {
    "AK": (Payroll("Unemployment insurance", .005, 2025, 51_700),),
    "CA": (Payroll("State disability insurance", .013, 2026),),
    "CO": (Payroll("FAMLI paid leave", .0044, 2026, SOCIAL_SECURITY_BASE),),
    "CT": (Payroll("Paid leave", .005, 2026, SOCIAL_SECURITY_BASE),),
    "DE": (Payroll("Paid leave", .004, 2026, SOCIAL_SECURITY_BASE),),
    "MA": (Payroll("Paid family and medical leave", .0046, 2026, SOCIAL_SECURITY_BASE),),
    "ME": (Payroll("Paid family and medical leave", .005, 2026, SOCIAL_SECURITY_BASE),),
    "MN": (Payroll("Paid leave", .0044, 2026, SOCIAL_SECURITY_BASE),),
    "NJ": (Payroll("Disability and family leave insurance", .0056, 2025, 165_400),
           Payroll("Unemployment and workforce funds", .00425, 2025, 43_300)),
    "NY": (Payroll("Paid family leave", .00432, 2026, 95_350), Payroll("Disability insurance", 0.0, 2026, flat=31.20)),
    "OR": (Payroll("Paid Leave Oregon", .006, 2026, SOCIAL_SECURITY_BASE), Payroll("Statewide transit tax", .001, 2026)),
    "PA": (Payroll("Unemployment insurance", .0007, 2026),),
    "RI": (Payroll("Temporary disability insurance", .012, 2025, 89_200),),
    "WA": (Payroll("Paid family and medical leave", .00808, 2026, SOCIAL_SECURITY_BASE), Payroll("WA Cares", .0058, 2026)),
}


@dataclass(frozen=True)
class LocalTax:
    """A city's, county's or district's income tax. `base` is what it's charged on: "wages", or "state" for the state's
    taxable income. `brackets` are (single, married), as for a state; `of_state_tax` is a share of the state's tax."""
    name: str
    state: str
    year: int
    brackets: tuple[Brackets, Brackets]
    base: str = "wages"
    of_state_tax: float = 0.0
    places: tuple[str, ...] = ()  # Places named in a posting's location that put a job under it. Matched as whole words.
    statewide: bool = False  # Charged nearly everywhere in the state, so it's counted wherever no city's own applies.
    note: str = ""


def _flat(rate: float) -> tuple[Brackets, Brackets]:
    return ((0, rate),), ((0, rate),)


# The local income taxes that change take-home most, each with the year of its rate. Many smaller ones are left out:
# most Ohio and Michigan cities, Kentucky's other occupational taxes, Iowa's school surtax, Denver's flat $5.75 a month.
LOCAL: dict[str, LocalTax] = {
    "nyc": LocalTax("New York City income tax", "NY", 2026,
                    (((0, .03078), (12_000, .03762), (25_000, .03819), (50_000, .03876)),
                     ((0, .03078), (21_600, .03762), (45_000, .03819), (90_000, .03876))), base="state",
                    places=("New York City", "New York, NY", "NYC", "Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")),
    "yonkers": LocalTax("Yonkers resident surcharge", "NY", 2026, ((), ()), of_state_tax=.1675, places=("Yonkers",)),
    "philadelphia": LocalTax("Philadelphia wage tax", "PA", 2026, _flat(.0374), places=("Philadelphia",)),
    "pittsburgh": LocalTax("Pittsburgh earned income tax", "PA", 2026, _flat(.03), places=("Pittsburgh",)),
    "pa": LocalTax("Local earned income tax", "PA", 2026, _flat(.01), statewide=True,
                   note="Most Pennsylvania towns and school districts together charge at least 1%."),
    "md": LocalTax("County income tax", "MD", 2026, _flat(.032), base="state", statewide=True,
                   note="3.2% is the rate in most of the populous counties. The range is 2.25% to 3.3%."),
    "in": LocalTax("County income tax", "IN", 2026, _flat(.015), statewide=True,
                   note="Every Indiana county charges one. 1.5% is near the middle of the range."),
    "indianapolis": LocalTax("Marion County income tax", "IN", 2026, _flat(.0202), places=("Indianapolis",)),
    "detroit": LocalTax("Detroit income tax", "MI", 2026, _flat(.024), places=("Detroit",)),
    "grand-rapids": LocalTax("Grand Rapids income tax", "MI", 2026, _flat(.015), places=("Grand Rapids",)),
    "columbus": LocalTax("Columbus income tax", "OH", 2026, _flat(.025), places=("Columbus",)),
    "cleveland": LocalTax("Cleveland income tax", "OH", 2026, _flat(.025), places=("Cleveland",)),
    "cincinnati": LocalTax("Cincinnati income tax", "OH", 2026, _flat(.018), places=("Cincinnati",)),
    "toledo": LocalTax("Toledo income tax", "OH", 2026, _flat(.025), places=("Toledo",)),
    "akron": LocalTax("Akron income tax", "OH", 2026, _flat(.025), places=("Akron",)),
    "dayton": LocalTax("Dayton income tax", "OH", 2026, _flat(.025), places=("Dayton",)),
    "kansas-city": LocalTax("Kansas City earnings tax", "MO", 2026, _flat(.01), places=("Kansas City",)),
    "st-louis": LocalTax("St. Louis earnings tax", "MO", 2026, _flat(.01), places=("St. Louis", "Saint Louis")),
    "louisville": LocalTax("Louisville occupational tax", "KY", 2026, _flat(.022), places=("Louisville",)),
    "lexington": LocalTax("Lexington occupational tax", "KY", 2026, _flat(.0225), places=("Lexington",)),
    "wilmington": LocalTax("Wilmington wage tax", "DE", 2026, _flat(.0125), places=("Wilmington",)),
    "birmingham": LocalTax("Birmingham occupational tax", "AL", 2026, _flat(.01), places=("Birmingham",)),
    # District taxes whose boundaries don't follow any one city's name, so a posting never puts a job under them. Name
    # them for your home under [relocation] home_local_taxes.
    "metro-shs": LocalTax("Metro supportive housing services tax", "OR", 2026,
                          (((0, 0.0), (125_000, .01)), ((0, 0.0), (200_000, .01))), base="state",
                          note="Charged on residents of the Metro district, in parts of three counties."),
    "multnomah-pfa": LocalTax("Multnomah County Preschool for All tax", "OR", 2026,
                              (((0, 0.0), (125_000, .015), (250_000, .03)), ((0, 0.0), (200_000, .015), (400_000, .03))),
                              base="state", places=("Multnomah",), note="Charged on residents of Multnomah County."),
}


def local_for(state: str, city: str) -> list[str]:
    """The LOCAL taxes a job in `city`, `state` comes under: the city's own, or else the state's statewide one."""
    own = [key for key, tax in LOCAL.items() if tax.state == state and city and any(
        re.search(rf"(?<!\w){re.escape(place)}(?!\w)", city, re.I) for place in tax.places)]
    return own or [key for key, tax in LOCAL.items() if tax.state == state and tax.statewide]


@dataclass
class TakeHome:
    """A year's wages and what's taken from them, each a positive number, in dollars."""
    wages: float
    state: str
    filing: str
    federal: float = 0.0
    fica: float = 0.0
    state_income: float = 0.0
    payroll: float = 0.0
    local: float = 0.0
    lines: list[tuple[str, float]] = field(default_factory=list)

    @property
    def taxes(self) -> float:
        return self.federal + self.fica + self.state_income + self.payroll + self.local

    @property
    def net(self) -> float:
        return self.wages - self.taxes


def _ct_adjust(wages: float, taxable: float, tax: float, filing: str) -> float:
    """Connecticut's 2% bracket is taxed at 4.5% as income rises, and two recaptures take back more of the lower
    brackets above $105k and $200k (single). Taxable income stands in for Connecticut AGI, which it nearly equals."""
    married = filing == "married"
    first = 20_000 if married else 10_000
    shrink = (2_000 if married else 1_000) * -(-max(0.0, wages - (100_500 if married else 56_500)) // 5_000)
    tax += min(first, shrink, taxable) * (.045 - .02)
    steps = lambda over, size: -(-max(0.0, wages - over) // size)  # Each step "or fraction thereof".
    if married:
        tax += min(500, 50 * steps(210_000, 10_000))
        tax += min(6_300, min(5_400, 180 * steps(400_000, 10_000)) + 100 * steps(1_000_000, 10_000))
    else:
        tax += min(250, 25 * steps(105_000, 5_000))
        tax += min(3_150, 90 * steps(200_000, 5_000) + 50 * steps(500_000, 5_000))
    return tax


NY_RECAPTURE_FROM, NY_RECAPTURE_OVER = 107_650, 50_000


def _ny_adjust(wages: float, taxable: float, tax: float, filing: str) -> float:
    """New York's recapture, approximately. Past $107,650 of income, the benefit of the brackets below each one that
    reaches past that is taken back over the next $50k of income, until everything is taxed at that bracket's rate.
    Each higher bracket starts its own $50k from where it begins."""
    if wages <= NY_RECAPTURE_FROM:
        return tax
    brackets = STATES["NY"].brackets(filing)
    for (start, rate), (top, _next) in zip(brackets, [*brackets[1:], (INF, 0.0)], strict=True):
        if taxable <= start or top <= NY_RECAPTURE_FROM:
            continue
        share = min(1.0, max(0.0, (wages - max(NY_RECAPTURE_FROM, start)) / NY_RECAPTURE_OVER))
        tax += (taxable * rate - tax) * share
    return tax


_ADJUST = {"CT": _ct_adjust, "NY": _ny_adjust}


def state_taxable(wages: float, state: str, filing: str = "single", federal_tax: float = 0.0) -> float:
    rules = STATES[state]
    deduction = _phased(_by_filing(rules.deduction, filing), wages,
                        _by_filing(rules.deduction_phaseout, filing) if rules.deduction_phaseout else None)
    exemption = _phased(_by_filing(rules.exemption, filing), wages,
                        _by_filing(rules.exemption_phaseout, filing) if rules.exemption_phaseout else None)
    federal = min(federal_tax, _by_filing(rules.federal_deduction, filing))
    federal = _phased(federal, wages, _by_filing(rules.federal_phaseout, filing) if rules.federal_phaseout else None)
    return max(0.0, wages - deduction - exemption - federal)


def state_income_tax(wages: float, state: str, filing: str = "single", federal_tax: float | None = None) -> float:
    """A state's income tax on wages. `federal_tax` is the federal income tax, for the states that deduct it."""
    rules = STATES[state]
    if not rules.single:
        return 0.0
    if federal_tax is None:
        federal_tax = federal_income_tax(wages, filing)
    taxable = state_taxable(wages, state, filing, federal_tax)
    tax = bracket_tax(taxable, rules.brackets(filing))
    if state in _ADJUST:
        tax = _ADJUST[state](wages, taxable, tax, filing)
    credit = _phased(_by_filing(rules.credit, filing), wages,
                     _by_filing(rules.exemption_phaseout, filing) if rules.exemption_phaseout else None)
    tax = max(0.0, tax - credit)
    if rules.floor_share and wages > rules.floor_share[0]:
        tax = max(tax, wages * rules.floor_share[1])
    return tax


def payroll_taxes(wages: float, state: str) -> list[tuple[str, float]]:
    return [(item.name, min(wages, item.cap) * item.rate + item.flat) for item in PAYROLL.get(state, ())]


def local_tax(key: str, wages: float, filing: str, state_taxable_income: float, state_tax: float) -> float:
    tax = LOCAL[key]
    if tax.of_state_tax:
        return state_tax * tax.of_state_tax
    base = state_taxable_income if tax.base == "state" else wages
    return bracket_tax(base, _by_filing(tax.brackets, filing))


def take_home(wages: float, state: str, filing: str = "single", local: tuple[str, ...] | list[str] = ()) -> TakeHome:
    """What `wages` leave after every tax this models, in `state` (its two-letter code), with the LOCAL taxes named."""
    if state not in STATES:
        raise ValueError(f"No tax table for '{state}'. Use a state's two-letter code, as in WI.")
    if filing not in FILINGS:
        raise ValueError(f"Filing status '{filing}' isn't one of {', '.join(FILINGS)}.")
    result = TakeHome(wages=wages, state=state, filing=filing)
    result.federal = federal_income_tax(wages, filing)
    result.fica = fica(wages, filing)
    result.state_income = state_income_tax(wages, state, filing, result.federal)
    payroll = payroll_taxes(wages, state)
    result.payroll = sum(amount for _name, amount in payroll)
    taxable = state_taxable(wages, state, filing, result.federal)
    locals_ = [(LOCAL[key].name, local_tax(key, wages, filing, taxable, result.state_income)) for key in local]
    result.local = sum(amount for _name, amount in locals_)
    result.lines = [("Federal income tax", result.federal), ("Social Security and Medicare", result.fica),
                    ("State income tax", result.state_income), *payroll, *locals_]
    return result


def solve_wages(target_net: float, state: str, filing: str = "single", local: tuple[str, ...] | list[str] = ()) -> float:
    """The wages whose take-home in `state` is `target_net`. Take-home rises with wages everywhere this models, save a
    few cliffs of a few dollars where an exemption ends, so halving the interval finds it to the dollar."""
    low, high = 0.0, max(1_000.0, target_net * 4)
    while take_home(high, state, filing, local).net < target_net:
        high *= 2
    while high - low > 0.5:
        middle = (low + high) / 2
        if take_home(middle, state, filing, local).net < target_net:
            low = middle
        else:
            high = middle
    return high
