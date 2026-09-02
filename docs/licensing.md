# Licensing

Four different licensing questions run through this project and they are
routinely confused with each other:

1. **The code.** What anyone may do with Academious itself.
2. **The source terms.** What each API's terms of use permit us to fetch,
   store and re-serve — a contract with the provider, independent of copyright.
3. **The content.** Who holds rights in the titles, abstracts and full texts we
   store, and under what licence each paper's own copy sits.
4. **The dependencies and the model.** What we have taken on by using them.

They are answered separately below, because a permissive answer to one says
nothing about the others: OpenAlex's metadata is CC0 *and* arXiv's terms still
forbid us re-serving the PDFs that metadata points at.

Storage policy and the OA resolution chain live in
[open-access.md](open-access.md); per-connector endpoints and quirks live in
[sources.md](sources.md). This document is the licensing view across both, plus
the obligations that follow from them.

**This is an engineering record, not legal advice.** Where a question needs a
lawyer, it says so rather than guessing.

---

## 1. The code: undecided, which means "all rights reserved"

There is no `LICENSE` file in the repository and no `license` field in
`pyproject.toml`. That is not a neutral default — absent a licence, exclusive
copyright applies, so nobody may copy, modify or redistribute the code, and a
public GitHub repository does not change that. GitHub's terms grant other users
the right to *view and fork* a public repository, and nothing more.

That is a decision not yet taken rather than a decision to keep it closed. It
has to be taken before any of these:

| Trigger | Why it forces the decision |
|---|---|
| Anyone else contributing | Without a licence there is no inbound grant, and their contribution is separately copyrighted |
| Publishing the repository as an example or portfolio piece | Readers cannot legally reuse anything they see |
| Any deployment somebody else runs | They need the right to run and modify it |

The dependency stack constrains the choice only mildly (§5): everything is
permissive except `psycopg`, which is LGPL-3.0 and is used as a library by a
network service rather than statically linked into a distributed binary. A
permissive licence (MIT, Apache-2.0) is available; Apache-2.0 additionally
grants patent rights, which matters more for a retrieval system than for a
website.

**Open — [PROD-003](backlog.md#prod-003).**

---

## 2. Source terms: what each provider permits

Terms of use are a contract with the provider. They bind us regardless of who
owns the copyright in the underlying paper, and they are the reason several
deliberate limits exist in the code.

| Source | Metadata licence | What the terms permit | What we do |
|---|---|---|---|
| **OpenAlex** | CC0 | Anything, no attribution required | Store metadata, topics, OA status |
| **arXiv** | Metadata reusable for discovery | Metadata retrieval, discovery tools, search interfaces, citation graphs. **Prohibits** redistributing e-prints or serving PDFs from our own servers unless licensed | Store metadata, link out. No full text, ever |
| **bioRxiv / medRxiv** | Per-paper licence code (`cc_by`, `cc_no`, `cc0`, …) | Metadata access; content per the paper's own licence | Store metadata and the licence code, link out |
| **Europe PMC** | Per-record | *"It is not permissible to use any kind of automated process to bulk download other content from Europe PMC"* — their protocols exist to serve the open-access subset and metadata | `ACADEMIOUS_EUROPEPMC_QUERIES` defaults to `OPEN_ACCESS:Y`, so the default harvest cannot leave the OA subset by accident |
| **Retraction Watch** (via Crossref) | **CC-BY 4.0** | Commercial use permitted **with attribution** | Download the whole dataset, diff it, set `retraction_status`. **Attribution is not currently given — see §4** |

Two of these are enforced in code rather than trusted to discipline:

* The Europe PMC default query is `OPEN_ACCESS:Y`. Widening it is a deliberate
  edit to configuration, and [sources.md](sources.md) records that the decision
  belongs to the terms rather than to convenience.
* The arXiv rate limit — one request per three seconds, one connection, across
  all machines — is a term of use, not a courtesy, and is enforced outbound.

---

## 3. Content: what we store, and on what basis

The full policy table is in
[open-access.md](open-access.md#what-we-may-store). In summary:

| Content | Stored? | Basis |
|---|---|---|
| Title, authors, venue, identifiers, dates | Yes | Facts and short factual metadata |
| Topics, keywords | Yes | Supplied as metadata by the source |
| **Abstract** | **Yes**, with attribution and a source link | **See the caveat below** |
| Full text under CC-BY / CC-BY-SA / CC0 | Permitted by policy | The licence permits it |
| Full text under CC-BY-NC | Permitted, flagged NC | Revisit if the project ever monetises |
| Any other full text | No | Includes most arXiv papers: the arXiv non-exclusive licence is not a CC licence |
| Retraction notices | Yes | CC-BY 4.0, attribution owed |

**Nothing stores full text today.** `fulltext_status` is `linked` or
`abstract_only` and never `stored`. Every discovered copy is an `oa_location`
row — a URL, a host type, a version and a licence — so what the corpus holds is
a pointer, not a copy.

### The abstract question is genuinely open

Abstracts are the one category where the policy asserts a conclusion the
project has not established. Publisher abstracts are frequently claimed as
copyrighted works, and Academious both **stores** them and **re-serves** them
through a public API: `GET /papers` returns a truncated preview and
`GET /papers/{id}` returns the abstract in full.

Arguments exist on both sides — abstracts are short, factual, published
precisely to be indexed, and every major discovery service redistributes them.
That is an argument from practice, not a legal basis, and the "Basis" column for
abstracts in `open-access.md` is empty for exactly that reason.

What is defensible today: the corpus is overwhelmingly preprints and
open-access literature whose abstracts are distributed under permissive terms by
the source itself, every abstract carries attribution and a link to the
original, and no paywalled publisher's abstract is served from a source whose
terms forbid it. What has not happened is a considered legal review, and this
document exists partly to stop that gap being invisible.

**Open — [PROD-004](backlog.md#prod-004).**

### Per-paper licences travel with the paper

`oa_location.licence` records what each copy is under, and the best-location
precedence prefers freer licences: `cc0 > cc-by > cc-by-sa > cc-by-nc >
everything else`. Two source-specific helpers exist because the preprint servers
encode licences differently — `sources/arxiv/normalise.is_open_licence` treats
only `creativecommons.org` and `publicdomain` URLs as open, so arXiv's default
`nonexclusive-distrib` is correctly *not* open.

A per-record `license` field never decides open-access status: Europe PMC
populates it on subscription-only articles too, which [sources.md](sources.md)
records as a verified quirk.

---

## 4. Obligations we are not currently meeting

Written plainly, because an unmet obligation nobody has written down is
indistinguishable from one nobody knows about.

### Retraction Watch attribution is owed and not given

The dataset is CC-BY 4.0. Commercial use is permitted **with attribution**, and
attribution is the whole of what the licence asks in return. Academious uses it
to set `retraction_status`, surfaced on paper cards and detail pages as a
retraction badge — a visible product feature derived directly from the dataset.

Searching the frontend for "Retraction Watch" returns nothing. Neither the site
footer, the paper detail page, nor the badge names the source. That is a licence
obligation unmet, and it is cheap to discharge: a credit line naming Retraction
Watch and Crossref, with a link, wherever retraction status is shown or in a
site-wide colophon.

**Open — [WEB-012](backlog.md#web-012).**

### The corpus description omits OpenAlex

`AppShell.tsx` tells readers the corpus is "recent research from arXiv,
bioRxiv/medRxiv and Europe PMC". OpenAlex supplies 46,012 of 108,886 papers —
42% of the corpus, and its largest single source. CC0 imposes no attribution
requirement, so this is not a licence breach; it is a factual error in
user-facing copy, and it belongs in the same fix.

---

## 5. Dependencies and the model

Inventoried from the installed distributions on 2026-09-03.

| Package | Version | Licence |
|---|---|---|
| fastapi | 0.141.1 | MIT |
| uvicorn | 0.52.4 | BSD-3-Clause |
| sqlalchemy | 2.0.52 | MIT |
| alembic | 1.19.1 | MIT |
| **psycopg** | **3.3.4** | **LGPL-3.0-only** |
| pydantic / pydantic-settings | 2.13.4 / 2.15.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| tenacity | 9.1.4 | Apache-2.0 |
| structlog | 26.1.0 | MIT OR Apache-2.0 |
| defusedxml | 0.7.1 | PSF |
| python-dateutil | 2.9.0 | Dual: Apache-2.0 or BSD-3-Clause |
| pgvector | 0.5.0 | MIT |
| numpy | 2.5.2 | BSD-3-Clause, with bundled 0BSD, MIT and Zlib components |
| slowapi | 0.1.10 | MIT |
| torch | 2.9.1+cpu | BSD-3-Clause |
| transformers | 4.57.6 | Apache-2.0 |
| adapters | 1.3.0 | Apache-2.0 |
| onnxruntime | 1.29.0 | MIT |

**`psycopg` is the only copyleft dependency.** LGPL-3.0 obliges us to let a
recipient replace the library and to convey its licence text — obligations that
attach to *distributing* the software. Academious is a network service: nobody
receives a copy, so nothing is triggered today. It would matter if the project
were ever shipped as a binary, a container image offered for download, or an
appliance. LGPL is not AGPL; running it as a service imposes nothing.

**SPECTER2** (`allenai/specter2_base` plus the proximity and ad-hoc query
adapters) is Apache-2.0, as recorded in [embeddings.md](embeddings.md). Model
weights are pinned by revision, which is a reproducibility control rather than a
licensing one, but it does mean the licensed artefact is identified exactly.

The frontend's dependencies are not inventoried here. They ship to browsers as
compiled bundles, which is distribution, so they warrant their own pass.

**Open — [PROD-005](backlog.md#prod-005).**

---

## 6. What this document does not cover

* **Privacy and data protection.** No personal data of *users* is collected —
  no accounts, no cookies, no query logging ([security.md](security.md)) — but
  the corpus contains authors' names, ORCIDs and affiliations, which is personal
  data about third parties under GDPR. Whether a research-purposes exemption
  applies has not been assessed. It becomes pressing with accounts (Phase 3).
* **Takedown process.** Phase 0 §14 planned a `legal.md` covering what we store
  and how a rights-holder asks for removal. There is no route today beyond
  contacting the maintainer, and no documented turnaround.
* **Trademarks.** "Academious" is not registered, and the source names used in
  the interface (arXiv, bioRxiv, Europe PMC) are other parties' marks, used
  nominatively to say where a paper came from. arXiv's terms specifically
  prohibit implying endorsement, which [open-access.md](open-access.md) already
  records.
