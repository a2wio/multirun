# build one article page in someone else's house style

Write a single blog article page — one self-contained HTML file at
`article/index.html` — in the visual language of pangram.com's landing
page. The landing page is marketing; what you're building is the
article page that site never had, and it has to look like it belongs
to the same site.

The reference is live at https://www.pangram.com/ — look at it if you
can reach it. Everything below was measured off it on 2026-08-12, so
the brief stands on its own if you can't.

## The house style, measured

Type — three families, no others:

- Headings: a high-contrast display serif. The site's own is licensed;
  use **Imbue** or **Playfair Display** from Google Fonts. Weight 400,
  never bold. h1 ~60px / line-height 1.2 / letter-spacing -1px; h2
  ~56px / 1.1 / -1.4px. The serif is the whole voice of the page —
  large, thin, tight.
- Body and UI: **IBM Plex Sans**, 16-18px, line-height 1.5-1.6,
  letter-spacing normal.
- Anything technical — code, data, model talk: **IBM Plex Mono**.

Color — the measured palette, hex exact:

    ink            #142020   headings, body on light
    ink alt        #212631   the hero heading only
    muted          #777777   captions, meta, timestamps
    page           #FFFFFF
    panel          #F8F7F6   cards, insets, quiet blocks
    hairline       #E2E8F0   1px borders, rules
    orange         #FF6106   CTAs, numerals, links on hover
    deep green     #0B2620   inverted section background
    green          #15502E   secondary buttons, accents on light
    pink           #F4BEFF   highlighter chips
    blue           #AAD8F9   highlighter chips, alternate

Layout and rhythm:

- Content column maxes at 1200px; running text measures 680-720px.
- 96-160px of air between sections. The page breathes more than you
  think it should.
- Cards: panel fill, 1px hairline border, 12px radius, no drop shadow.
- Section eyebrows are a highlighter chip: small IBM Plex Sans, ~13px,
  on a pink or blue block, tight padding, square or 4px corners.
- Numbered lists of anything are `01 02 03` — serif, orange, sitting
  beside a serif heading, not above it.
- At least one full-bleed inverted band: deep green background, white
  serif heading, IBM Plex Mono body. The site uses this for the
  technical middle of the page and so should you.
- Orange is the only loud color and it is used sparingly: primary CTA,
  the numerals, one or two links. Never an orange heading.

Voice, if you write copy: plain, specific, confident, numbers over
adjectives. No hype, no exclamation marks, no "unlock" or "empower".

## What the page has to contain

An article, not a template skeleton. Subject:

> **Why perplexity-based AI detection stopped working**

Write the article. 800-1200 words of real prose that says something —
not lorem, not placeholder, not five headings with a sentence under
each. Assume a reader who is technical but not an ML researcher.

The page must have all of:

1. A minimal header: wordmark on the left, three or four nav items,
   one orange CTA on the right.
2. Title, a one-sentence dek under it, and a byline line with author,
   date and read time.
3. The body, with at least two subheadings.
4. One pull quote, set in the display serif.
5. One figure that carries information — a table, a chart drawn in
   inline SVG, or a diagram. Not a stock image, not an `<img>` to a
   URL. If it has numbers in it, invent plausible ones and say in the
   caption that they're illustrative.
6. One block of code or monospace data, in IBM Plex Mono.
7. The inverted deep-green band, used for whatever section of the
   article earns it.
8. A footer with three related-article cards and a short site footer.

## Constraints

- **One file.** `article/index.html`, self-contained: all CSS in a
  `<style>` block, any JS inline. The only external requests allowed
  are Google Fonts and inline `data:` URIs. No local stylesheet, no
  local script, no local image file — the page is going to be rendered
  in an iframe beside seven others and every one of them has to work
  from that single file alone.
- Responsive: it must not overflow horizontally at 390px wide.
- Do not touch anything else in this repo. One new file, one directory.
- The database in this run is irrelevant to the task. Ignore it.

When you're done, say in two or three sentences what you decided about
the design and what you'd change with more time.
