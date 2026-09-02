"""Whether a publication date is one a paper could actually have.

The feed is ordered `published_date DESC`, so a wrong date is not a cosmetic
metadata problem: it is a permanent claim on the first page. A record dated
2050 sits above every real paper for twenty-four years, and nothing about the
row looks broken while it does.

Measured on the live corpus on 2026-09-03: **607 papers dated in the future,
every one of them from OpenAlex.** The distribution is what decides the rule:

    2026    414     the rest of this year
    2027     95
    2028     55
    2029+    43     thinning out to a single paper dated 2050-02-21

The first group is not an error. Journals postdate issues routinely - an
article published in September carries a December issue date, and a January
issue ships in November. Rejecting future dates outright would throw away
correct metadata for thousands of legitimately forthcoming papers.

So the rule is a **horizon, not a ban**: a date more than a year ahead of
ingestion is not plausible as an issue date and is treated as *unknown*. The
raw payload keeps whatever upstream said - `source_record` is immutable, so
nothing is lost and the decision can be replayed - and the paper falls to the
end of a `NULLS LAST` ordering instead of the top.

One year, rather than a tighter bound, because postdating past the following
calendar year is rare but real (annual volumes, delayed proceedings), and the
cost of the two errors is not symmetric: dropping a real date costs one paper
its position in the feed, while trusting a fabricated one costs every reader
the front page.

There is no lower bound. Early dates are genuinely old literature - the corpus
holds the *Edinburgh medical journal* back to the 1800s - and a paper dated too
early sinks in the feed rather than dominating it, which is the failure mode
that does not need a policy.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from academious.core.logging import get_logger
from academious.sources.base import PaperCandidate

log = get_logger(__name__)

#: How far ahead of ingestion a publication date may sit and still be believed.
FUTURE_HORIZON_DAYS = 365


def is_plausible(value: date | None, *, today: date | None = None) -> bool:
    """Whether `value` is a date a paper could carry. `None` is plausible."""
    if value is None:
        return True
    horizon = (today or date.today()) + timedelta(days=FUTURE_HORIZON_DAYS)
    return value <= horizon


def sanitise(candidate: PaperCandidate, *, today: date | None = None) -> PaperCandidate:
    """Return the candidate with implausible dates cleared.

    Applied once in the pipeline rather than in each connector: a rule enforced
    in four places is a rule the fifth connector will not have.
    """
    published_ok = is_plausible(candidate.published_date, today=today)
    online_ok = is_plausible(candidate.first_seen_online, today=today)
    if published_ok and online_ok:
        return candidate

    log.info(
        "ingest.implausible_date",
        source=candidate.source_key,
        doi=candidate.primary_doi,
        published_date=None if published_ok else str(candidate.published_date),
        first_seen_online=None if online_ok else str(candidate.first_seen_online),
    )
    return replace(
        candidate,
        published_date=candidate.published_date if published_ok else None,
        first_seen_online=candidate.first_seen_online if online_ok else None,
    )
