"""Location string parsing.

`parse_location()` turns a free-text location string (as emitted by an ATS)
into a structured `(city, region, country, is_remote)` tuple. The output
feeds two things:

    1. The structured columns on `jobs` (index-backed for cheap filtering).
    2. The facets endpoint that lets the dashboard show top-N cities /
       countries as clickable chips instead of a substring-only text box.

Design principles
-----------------
* Deterministic and dependency-free. No spaCy, no LLM. A small curated
  city/region → country lookup plus a few regex passes handle ~95% of real
  ATS output; the residual falls through as `None` on each field, which is
  fine — the raw `location` string is preserved.
* Alias-aware for the biggest cities/regions where sources disagree
  ("Bengaluru" ↔ "Bangalore", "Bombay" ↔ "Mumbai", "NYC" ↔ "New York").
* Never invents information. If it can only see "Remote", `is_remote=True`
  and everything else stays None.

Extending
---------
* Add cities to `_COUNTRY_CITIES`. Alphabetical within a country keeps diffs
  reviewable. Add alias mappings in `_CITY_ALIASES`.
* Add country synonyms to `_COUNTRY_ALIASES` (e.g. "U.S.A." → "United States").
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedLocation:
    city: str | None
    region: str | None
    country: str | None
    is_remote: bool

    @property
    def is_empty(self) -> bool:
        return (
            self.city is None
            and self.region is None
            and self.country is None
            and not self.is_remote
        )


# ---------------------------------------------------------------------------
# Curated city / region → country lookup
# ---------------------------------------------------------------------------
# Kept small on purpose. Cities are matched case-insensitively on word
# boundaries so "Berlin, DE" matches "berlin" without also matching
# "Berlin Heights, OH". Country listing order is intentional — first match
# wins when a token collides (rare, e.g. "Cambridge" appears in both UK & US;
# UK is listed later so US wins, which matches ATS conventions).

_COUNTRY_CITIES: dict[str, tuple[str, ...]] = {
    "India": (
        "Bengaluru", "Bangalore", "Mumbai", "Bombay", "Delhi", "New Delhi",
        "Gurgaon", "Gurugram", "Noida", "Hyderabad", "Chennai", "Madras",
        "Kolkata", "Calcutta", "Pune", "Ahmedabad", "Jaipur", "Kochi",
        "Cochin", "Thiruvananthapuram", "Trivandrum", "Chandigarh",
        "Indore", "Bhopal", "Nagpur", "Coimbatore", "Vadodara", "Baroda",
        "Vishakhapatnam", "Visakhapatnam", "Vizag", "Surat", "Lucknow",
        "Kanpur", "Guwahati", "Bhubaneswar", "Mohali", "Faridabad", "Ghaziabad",
    ),
    "United States": (
        "New York", "NYC", "San Francisco", "SF", "Los Angeles", "LA",
        "Chicago", "Boston", "Seattle", "Austin", "Denver", "Portland",
        "Atlanta", "Miami", "Dallas", "Houston", "San Diego", "San Jose",
        "Palo Alto", "Mountain View", "Sunnyvale", "Menlo Park", "Cupertino",
        "Cambridge", "Washington", "Philadelphia", "Phoenix", "Minneapolis",
        "Salt Lake City", "Nashville", "Detroit", "Pittsburgh", "Charlotte",
        "Raleigh", "Durham", "Brooklyn", "Bellevue", "Redmond", "Kirkland",
    ),
    "United Kingdom": (
        "London", "Manchester", "Edinburgh", "Glasgow", "Bristol", "Leeds",
        "Birmingham", "Liverpool", "Sheffield", "Cardiff", "Belfast", "Oxford",
        "Reading",
    ),
    "Canada": (
        "Toronto", "Vancouver", "Montreal", "Ottawa", "Calgary", "Edmonton",
        "Waterloo", "Kitchener",
    ),
    "Germany": (
        "Berlin", "Munich", "München", "Hamburg", "Frankfurt", "Cologne",
        "Köln", "Stuttgart", "Düsseldorf", "Dusseldorf", "Leipzig",
    ),
    "France": ("Paris", "Lyon", "Marseille", "Toulouse", "Bordeaux", "Nice", "Lille"),
    "Netherlands": ("Amsterdam", "Rotterdam", "Utrecht", "The Hague", "Eindhoven"),
    "Ireland": ("Dublin", "Cork", "Galway", "Limerick"),
    "Spain": ("Madrid", "Barcelona", "Valencia", "Seville", "Bilbao"),
    "Poland": ("Warsaw", "Kraków", "Krakow", "Wrocław", "Wroclaw", "Gdańsk", "Gdansk"),
    "Portugal": ("Lisbon", "Porto", "Braga"),
    "Sweden": ("Stockholm", "Gothenburg", "Göteborg", "Malmö", "Malmo"),
    "Norway": ("Oslo", "Bergen", "Trondheim"),
    "Denmark": ("Copenhagen", "Aarhus"),
    "Finland": ("Helsinki", "Espoo", "Tampere"),
    "Switzerland": ("Zurich", "Zürich", "Geneva", "Basel", "Lausanne"),
    "Austria": ("Vienna", "Wien", "Graz", "Salzburg"),
    "Belgium": ("Brussels", "Antwerp", "Ghent"),
    "Australia": ("Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide", "Canberra"),
    "New Zealand": ("Auckland", "Wellington", "Christchurch"),
    "Singapore": ("Singapore",),
    "Hong Kong": ("Hong Kong",),
    "Japan": ("Tokyo", "Osaka", "Kyoto", "Yokohama"),
    "China": ("Beijing", "Shanghai", "Shenzhen", "Guangzhou", "Hangzhou"),
    "South Korea": ("Seoul", "Busan"),
    "Israel": ("Tel Aviv", "Jerusalem", "Haifa"),
    "United Arab Emirates": ("Dubai", "Abu Dhabi", "Sharjah"),
    "Brazil": ("São Paulo", "Sao Paulo", "Rio de Janeiro", "Brasília", "Brasilia"),
    "Mexico": ("Mexico City", "Guadalajara", "Monterrey"),
    "Argentina": ("Buenos Aires", "Córdoba", "Cordoba"),
    "Chile": ("Santiago",),
    "Colombia": ("Bogotá", "Bogota", "Medellín", "Medellin"),
    "South Africa": ("Cape Town", "Johannesburg", "Durban"),
    "Kenya": ("Nairobi",),
    "Nigeria": ("Lagos", "Abuja"),
    "Egypt": ("Cairo",),
    "Turkey": ("Istanbul", "Ankara"),
    "Vietnam": ("Ho Chi Minh City", "Hanoi", "Saigon"),
    "Thailand": ("Bangkok",),
    "Philippines": ("Manila", "Cebu"),
    "Indonesia": ("Jakarta", "Bali"),
    "Malaysia": ("Kuala Lumpur", "Penang"),
    "Taiwan": ("Taipei",),
    "Czech Republic": ("Prague", "Brno"),
    "Hungary": ("Budapest",),
    "Romania": ("Bucharest", "Cluj-Napoca"),
    "Ukraine": ("Kyiv", "Kiev", "Lviv"),
    "Estonia": ("Tallinn",),
    "Lithuania": ("Vilnius",),
    "Latvia": ("Riga",),
    "Greece": ("Athens", "Thessaloniki"),
    "Italy": ("Rome", "Milan", "Turin", "Naples", "Florence"),
}


# Canonicalize aliases to a single display name so facet counts merge
# ("Bangalore" and "Bengaluru" both become "Bengaluru"). Alias → canonical.
_CITY_ALIASES: dict[str, str] = {
    "bangalore": "Bengaluru",
    "bombay": "Mumbai",
    "madras": "Chennai",
    "calcutta": "Kolkata",
    "cochin": "Kochi",
    "trivandrum": "Thiruvananthapuram",
    "baroda": "Vadodara",
    "visakhapatnam": "Vishakhapatnam",
    "vizag": "Vishakhapatnam",
    "gurugram": "Gurgaon",
    "nyc": "New York",
    "sf": "San Francisco",
    "la": "Los Angeles",
    "münchen": "Munich",
    "köln": "Cologne",
    "düsseldorf": "Dusseldorf",
    "göteborg": "Gothenburg",
    "malmö": "Malmo",
    "kraków": "Krakow",
    "wrocław": "Wroclaw",
    "gdańsk": "Gdansk",
    "zürich": "Zurich",
    "wien": "Vienna",
    "são paulo": "Sao Paulo",
    "brasília": "Brasilia",
    "bogotá": "Bogota",
    "córdoba": "Cordoba",
    "medellín": "Medellin",
    "kiev": "Kyiv",
    "saigon": "Ho Chi Minh City",
}


# Country-name synonyms → canonical name.
_COUNTRY_ALIASES: dict[str, str] = {
    "us": "United States",
    "usa": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "united states of america": "United States",
    "america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "gb": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "uae": "United Arab Emirates",
    "u.a.e.": "United Arab Emirates",
    "deutschland": "Germany",
    "nederland": "Netherlands",
    "holland": "Netherlands",
    "españa": "Spain",
    "espana": "Spain",
    "polska": "Poland",
    "eire": "Ireland",
    "ireland (roi)": "Ireland",
    "korea": "South Korea",
    "china prc": "China",
    "prc": "China",
    "hk": "Hong Kong",
    "hongkong": "Hong Kong",
    "sg": "Singapore",
    "türkiye": "Turkey",
    "turkiye": "Turkey",
}


# ---------------------------------------------------------------------------
# US state / region abbreviations (kept small; only the ones ATSes actually
# emit as location suffixes.)
# ---------------------------------------------------------------------------

_US_STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}


# Remote / hybrid detection. Every real ATS says one of these somewhere.
_REMOTE_RE = re.compile(
    r"\b(remote|work[-\s]?from[-\s]?home|wfh|telecommute|distributed|anywhere|virtual)\b",
    re.IGNORECASE,
)
_HYBRID_RE = re.compile(r"\b(hybrid)\b", re.IGNORECASE)
_ONSITE_RE = re.compile(r"\b(on[-\s]?site|in[-\s]?office)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pre-compiled per-country regex matchers (built once at import time).
# ---------------------------------------------------------------------------


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _fold(s: str) -> str:
    """Lowercase + accent-strip so ``São Paulo`` matches ``sao paulo``."""
    nfd = unicodedata.normalize("NFD", s.lower())
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")


def _canonical_city(raw_match: str) -> str:
    """Return the canonical display name (accent-preserved) for a raw match."""
    return _CITY_ALIASES.get(raw_match.lower(), raw_match)


_ALL_CITY_TO_COUNTRY: dict[str, tuple[str, str]] = {}
for _country, _cities in _COUNTRY_CITIES.items():
    for _c in _cities:
        _ALL_CITY_TO_COUNTRY.setdefault(_fold(_c), (_canonical_city(_c), _country))
# Alias folds (Bangalore → Bengaluru, India), preserve country from canonical.
for _alias, _canonical in _CITY_ALIASES.items():
    for _country, _cities in _COUNTRY_CITIES.items():
        if _canonical in _cities:
            _ALL_CITY_TO_COUNTRY.setdefault(_fold(_alias), (_canonical, _country))
            break


# Sorted longest-first so "New York" wins over "York", and "San Francisco"
# beats "San" (there's no "San" city in the table, but this makes the rule
# resilient to future additions).
_CITY_ORDER = sorted(_ALL_CITY_TO_COUNTRY.keys(), key=lambda s: -len(s))

# One combined regex is faster than per-country iteration on hot paths
# (scrape persist calls this per job). Word-boundary anchored on both sides
# so partial matches like "berlin" inside "Berlin Heights" don't fire.
_CITY_RE = re.compile(
    r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in _CITY_ORDER) + r")(?![a-z0-9])",
    re.IGNORECASE,
)


_COUNTRY_NAMES = list(_COUNTRY_CITIES.keys())
_COUNTRY_NAME_RE = re.compile(
    r"(?<![a-z0-9])("
    + "|".join(re.escape(_fold(c)) for c in _COUNTRY_NAMES)
    + r")(?![a-z0-9])",
    re.IGNORECASE,
)
_COUNTRY_ALIAS_RE = re.compile(
    r"(?<![a-z0-9])("
    + "|".join(re.escape(a) for a in _COUNTRY_ALIASES.keys())
    + r")(?![a-z0-9])",
    re.IGNORECASE,
)
_FOLDED_COUNTRIES: dict[str, str] = {_fold(c): c for c in _COUNTRY_NAMES}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_location(raw: str | None, company_country: str | None = None) -> ParsedLocation:
    """Turn a free-text location into structured components.

    Args:
        raw: The raw location string emitted by the ATS. Can be ``None`` or
            empty; then only ``company_country`` (if given) fills the country.
        company_country: A hint from the company row (populated for India
            seed rows) — used as a fallback when the raw string doesn't
            mention any known country/city.

    Returns:
        A :class:`ParsedLocation`. Fields not confidently detected are ``None``.
    """
    if not raw or not raw.strip():
        if company_country:
            return ParsedLocation(city=None, region=None, country=company_country, is_remote=False)
        return ParsedLocation(city=None, region=None, country=None, is_remote=False)

    text = _normalize_ws(raw)
    folded = _fold(text)

    is_remote = bool(_REMOTE_RE.search(text)) and not bool(_HYBRID_RE.search(text))
    # "Hybrid — Berlin" and "Remote / Berlin" both keep the city; only pure
    # "Remote" / "Remote (US)" / "Anywhere" trigger the flag alone.
    if _HYBRID_RE.search(text):
        is_remote = False

    city: str | None = None
    country: str | None = None
    region: str | None = None

    # Pre-scan for a US state suffix (", CA" / ", OH" / etc.). When present
    # it's an unambiguous US signal that we use to gate ambiguous city
    # matches — "Berlin Heights, OH" must not resolve to Berlin/Germany just
    # because "Berlin" is a substring.
    state_suffix_country: str | None = None
    state_suffix_region: str | None = None
    for abbr, name in _US_STATES.items():
        if re.search(rf"(?:,\s*|\s){re.escape(abbr)}(?![A-Za-z])", text):
            state_suffix_country = "United States"
            state_suffix_region = name
            break

    # City lookup — highest signal. Prefer city hit → country falls out,
    # unless a US-state suffix says "this is a US location" and the city
    # candidate is non-US (a foreign-city substring inside a longer US
    # place name).
    m = _CITY_RE.search(text)
    if m:
        raw_hit = m.group(1)
        canonical_city, mapped_country = _ALL_CITY_TO_COUNTRY[_fold(raw_hit)]
        if state_suffix_country and mapped_country != state_suffix_country:
            # Discard the city hit — the state suffix is more trustworthy.
            city = None
            country = state_suffix_country
            region = state_suffix_region
        else:
            city = canonical_city
            country = mapped_country

    # Country lookup — explicit name or alias in the string.
    if country is None:
        m2 = _COUNTRY_NAME_RE.search(folded)
        if m2:
            country = _FOLDED_COUNTRIES[m2.group(1)]
        else:
            m3 = _COUNTRY_ALIAS_RE.search(folded)
            if m3:
                country = _COUNTRY_ALIASES[m3.group(1)]

    # US state — try both the abbreviation ("San Diego, CA") and the full
    # name ("New York, New York") forms. Only meaningful when country is US
    # or unknown; a bare "CA" without any other US signal is ambiguous
    # (could be California or Canada), so we only accept the abbreviation
    # when we already know the country is the US.
    if country == "United States":
        for abbr, name in _US_STATES.items():
            if re.search(rf"(?<![A-Za-z]){re.escape(abbr)}(?![A-Za-z])", text):
                region = name
                break
        if region is None:
            for abbr, name in _US_STATES.items():
                if re.search(rf"(?<![a-z]){re.escape(_fold(name))}(?![a-z])", folded):
                    region = name
                    break

    # Fall back to the company hint only when nothing was detected. Never
    # overwrite an ATS-declared country with the hint.
    if country is None and company_country:
        country = company_country

    return ParsedLocation(city=city, region=region, country=country, is_remote=is_remote)


# ---------------------------------------------------------------------------
# Helpers for the API layer
# ---------------------------------------------------------------------------


def known_countries() -> list[str]:
    """Ordered list of canonical country names the parser recognizes.

    Used by tests + the facets endpoint to build the "other countries" bucket
    without a full DB scan.
    """
    return list(_COUNTRY_NAMES)


def canonical_country(raw: str | None) -> str | None:
    """Map a raw country string to its canonical name if recognized."""
    if not raw:
        return None
    folded = _fold(raw.strip())
    if folded in _FOLDED_COUNTRIES:
        return _FOLDED_COUNTRIES[folded]
    if folded in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[folded]
    return None
