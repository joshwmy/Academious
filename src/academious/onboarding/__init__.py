"""Research profile creation: turning a person into a recommender input.

This package is the first stage of the recommendation system rather than a form
in front of it. A weak profile makes a good ranker look bad, and no amount of
ranking work recovers from an interest model that never captured what the reader
meant - so profile construction is measured, tested and documented on the same
terms as everything downstream of it.

| Module | Holds |
|---|---|
| `levels.py` | Human choices to recommender numbers. The only place numbers are written. |
| `draft.py` | `ProfileDraft`: what the reader chose, in their own words, plus validation. |
| `builder.py` | `ProfileBuilder`: draft to canonical `InterestProfile`, with provenance. |
| `refine.py` | Deterministic corrections applied to a draft after a preview. |
| `summary.py` | The built profile described back to the reader, with no model involved. |

```
ProfileDraft --> validate --> ProfileBuilder --> InterestProfile --> build_feed --> preview
      ^                                                 |
      +---------------------- refine <------------------+
```

**Stateless, and structured so that staying stateless is not a limitation.**
Nothing here persists anything or knows what a user is. The client holds the
draft between requests and sends it back; the server normalises, builds,
previews and forgets. When accounts arrive, the thing to store is the draft and
the profile it produced - not a rewrite of this package, because the draft is
already the durable, portable, human-readable artifact and the profile is
already derived from it.

**There is no separate serialisation module, deliberately.** The request and
response models in `api/schemas_profiles.py` *are* the JSON schema: a draft is
exactly what a client posts, so a second serialiser here would be a copy of it
that could drift. `PROFILE_SCHEMA_VERSION` travels in the response so a draft a
client stored today can be recognised by a server later.
"""

from __future__ import annotations

#: Version of the draft/profile JSON contract. Bumped when a change would make a
#: stored draft mean something different - a renamed level, a removed field, a
#: changed default. Adding an optional field does not bump it, because an old
#: draft still means what it meant.
PROFILE_SCHEMA_VERSION = 1

__all__ = ["PROFILE_SCHEMA_VERSION"]
