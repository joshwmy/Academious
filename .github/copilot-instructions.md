# Repository Instructions

UI work in this repository must follow the design direction in
`.impeccable.md`. The summary below is intentionally kept aligned with that
file so implementation work receives one consistent brief.

## Design Context

### Users

Academious serves lecturers, researchers and students who want relevant papers
brought to them without the noise and repeated effort of a traditional research
database. The experience should feel like a calm daily reading ritual: open the
product, scan a considered selection, save useful work and move on.

### Brand Personality

**Focused, approachable, contemporary.**

The product should be academically credible but never institutional or
intimidating. Clarity, restraint and useful personalisation are the primary
signals of quality.

### Aesthetic Direction

Build a clean, minimalist academic SaaS workspace with a primarily white and
off-white interface, soft lavender states, muted violet accents, generous
whitespace and a clean sans-serif typeface similar in character to Inter.

Use a desktop-first layout with a persistent left sidebar containing Home,
Papers, Collections, Interests, Profile and Settings, with Settings anchored at
the bottom. The active item uses a pale lavender background.

The default content area begins with **Recommended for you** and **Research
tailored to your interests.** Show papers in a single vertical feed of compact,
rounded white cards with thin grey borders, minimal shadows and comfortable
padding. Each card includes a title, authors, publication source, relative date,
small lavender topic tags and a quiet bookmark action.

The brand mark is a lowercase “a” in a rounded square with a restrained
blue-to-purple gradient, paired with a lowercase dark-navy wordmark. Keep this
gradient limited to the logo.

Use these provisional palette values:

- White: `#FFFFFF`
- Off-white: `#F7F7FA`
- Lavender: `#EEEEFF`
- Violet: `#7770EC`
- Navy: `#171B2E`
- Grey: `#858895`

These values were inferred from a promotional mockup and must be calibrated for
WCAG 2.2 AA contrast during implementation.

Avoid dense analytics, database-table aesthetics, heavy shadows, glass effects,
ornamental gradients, loud social engagement patterns and excessive controls.
The visual references are Notion's workspace clarity, Linear's restraint and a
Spotify-like personalised discovery model, without directly copying them.

### Design Principles

1. Prioritise passive, personalised research discovery.
2. Let paper titles and research metadata lead the hierarchy.
3. Keep the main feed calm, linear and easy to scan.
4. Make personalisation understandable and editable.
5. Use lavender and violet only for meaningful states and brand moments.
6. Keep navigation stable and secondary actions quiet.
7. Preserve semantic structure, keyboard access, visible focus and WCAG 2.2 AA
   contrast.
8. Treat the reference as a promotional mockup: design and test interactions,
   edge cases and responsive behaviour instead of assuming them.
