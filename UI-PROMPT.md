# UI generation prompt — ControlPlane, light theme

Paste everything below the line into your design tool. It is written to be
self-contained: the tool does not need this repo.

---

## THE PRODUCT

**ControlPlane** is a governance checkpoint that sits between a company's
applications and an outside AI model provider. Every request and every response
passes through it. Real customer data is swapped for placeholders before it is
sent out, and swapped back when the answer returns — so the provider never
receives a real name, email, or account number.

**Who uses this dashboard:** a compliance officer, a CISO, or a data protection
lead at a bank or insurer. They are sceptical by profession. They want to see
evidence, not marketing. Every number on this dashboard was computed live by
the system; nothing is a summary someone typed in.

Design a **light, calm, confident enterprise dashboard**. It should feel like a
well-made modern SaaS product — approachable and clean — not like a security
console.

---

## VISUAL DIRECTION

Light, airy, generous. Soft shapes, lots of white space, almost no hard lines.

### Colour

| Token | Value | Use |
|---|---|---|
| Page background | `#F1F3F7` — very light cool grey | behind everything |
| Surface | `#FFFFFF` | every card |
| Ink | `#111318` — near-black, not pure black | headings, active pills |
| Body text | `#3F4552` | paragraphs |
| Muted text | `#8A91A0` | labels, captions, axis ticks |
| Hairline | `#E7EAF0` | dividers, input borders, chart gridlines |
| **Warm / inside** | `#F97316` orange, tint `#FFF1E6` | see the semantic rule below |
| **Cool / outside** | `#2563EB` blue, tint `#E8EFFD` | see the semantic rule below |
| Amber / holding | `#F59E0B`, tint `#FEF3C7` | text being held back |
| Red / stopped | `#DC2626`, tint `#FEE9E9` | blocked |
| Green / verified | `#16A34A`, tint `#E7F6EC` | checks that passed |
| Violet | `#7C3AED` | at most one primary action per screen |

Optional: a very soft orange→blue gradient wash behind the app frame, visible
only at the outer edges. Use it once, on the login or hero framing. Not inside
the dashboard.

### Shape and depth

- Cards: **28px** radius, pure white, **no border** — separated by a soft
  diffuse shadow: `0 2px 20px rgba(17,19,24,0.05)`
- Buttons and filter chips: **fully rounded pills**
- Inputs and text areas: **16px** radius, 1px hairline border, white fill
- Icon buttons: **44px circles**, white, hairline border
- Nothing has a heavy border. Depth comes from shadow and white-on-grey.

### Type

Geometric sans throughout — **Poppins**, **Outfit**, or **Plus Jakarta Sans**.

- Page eyebrow: 15px, regular, muted grey — a short sentence above the title
- Page title: **52px, bold, tight letter-spacing (-0.02em)**
- Card title: 20px, semibold
- Body: 15px
- Label / caption: 13px, muted
- Big statistic: **40px bold**, with a 13px muted label under it
- Any text that represents *wire content* — a prompt, a model reply, a hash —
  is monospace (JetBrains Mono or similar), 14px, 1.7 line height

### Layout

- **Left icon rail**, ~80px wide, floating: a solid dark circular logo at the
  top, then a vertical column of white circular icon buttons. Active button =
  solid near-black circle with a white icon.
- **Top bar**: page title block on the left; a pill segmented control and a
  fully-rounded white search field on the right.
- Content on a 12-column grid, **24px gaps**, **32px padding inside cards**.
- Let cards breathe. Empty space is part of the design.

---

## THE ONE RULE THAT CANNOT BE CHANGED

This is the product's entire argument, expressed as colour:

> **Orange means a real value, and it lives inside the building.**
> **Blue means a placeholder, and it is the only thing allowed outside.**

Anywhere the interface shows data crossing to the model provider, there is a
**vertical divider** down the middle of the card. Real values (orange) appear
only on the left of it. Placeholders (blue) appear only on the right. When a
request is stopped, the divider turns red.

Do not use orange and blue decoratively anywhere else. They carry meaning here.
A viewer with the sound off should be able to follow a value going out cold and
coming back warm.

---

## SCREENS TO DESIGN

Five. Use the exact copy and numbers given — they are real output.

### 1 · Transit — the main screen

Eyebrow: `Watch one request cross the line`
Title: `Transit`

**Row of five selectable scenario cards** (white pills/cards, one selected with
an orange tint and orange border):
`The round trip` · `The credential` · `The landmine` · `The edge of governance` ·
`The same finding, a stricter route`
Each has a one-line grey subtitle, e.g. *"Substitution, not redaction — and the
number survives it"*.

**A prompt box**: white, 16px radius, monospace, ~6 lines tall. Below it a row
with a dropdown (`internal-knowledge`), a solid dark **Send request** button,
and two small grey info pills: `fp c1b31dfccac9a48f · policy v1` and
`interactive · commit at 40 tok / 250ms · hold 50 chars`.

**The centrepiece — one wide card split by the vertical divider.**

Left header: `INSIDE THE BUILDING` (orange)
Right header: `OUTSIDE · THE MODEL PROVIDER` (blue), with a green check chip:
`✓ leak check · 0 of 2 real values present`

Four quadrants, laid out as a **clockwise circuit** — top-left → top-right →
bottom-right → bottom-left. Number them 01–04:

- **01 What you sent** (top left) — monospace prompt with `Priya Sharma` and
  `priya.sharma@example.com` highlighted in orange. Below it, two finding rows:
  `customer_name — matched customer:44219 — 1.00` and
  `email — matched customer:44219 — 1.00`
- **02 What the provider received** (top right) — the same text with
  `[[CUST_A]]` and `[[EMAIL_A]]` as blue chips. The number `45230` is
  **unchanged and unhighlighted** — this is the point, the number crosses
  untouched.
- **03 What the model wrote** (bottom right) — a streaming reply still using
  the blue placeholders, with a small chip `commit 11 · flush`
- **04 What you read** (bottom left) — the same reply with the real values back
  in orange. A green check bar underneath: `✓ 2 values restored · 0 unrestored`

**Three cards underneath:**

- `Decision` — badge `allow`; two rows reading `customer_name — mitigated by
  substitution — allow`
- `After delivery · reversible harms` — a finding card:
  `entity_not_in_source`, badge `annotate`, evidence line, and two grey
  monospace lines: `confidence 0.65 = min(0.9, 0.55 + 0.1 × entities_without_provenance)`
  and `arrived 0ms after the reader had the answer`
- `Cost of this request` — two big statistics side by side:
  **$0.00044** *what we paid, routed* and **$0.00219** *baseline · claude-opus-5*

**At the bottom, "The tape"** — a dense monospace log table, four columns:
elapsed ms, sequence number, stage name, detail. Stage names are colour-coded
by side (orange / blue / red). Rows are compact, 28px tall, hairline separated.

### 2 · Profiles

Eyebrow: `Three use cases, three policies, one checkpoint`
Title: `Profiles`

Three equal cards: `customer-support`, `decision-support`, `internal-knowledge`.
Each shows a description, a monospace fingerprint chip, and a list of
label→value rows: `blocks at confidence 0.75`, `review band 0.35 – 0.75`,
`flag budget / 100 · 5`, `streaming interactive`, `hold window 50 chars`.
Two small pill buttons at the bottom: `Tighten by 0.15`, `Switch to throughput`.

Below: a **diff table** — three columns *Path · Was · Now* — where the "Now"
value is orange. Header shows `fingerprint c1b31dfc… → 8e02a4b1…`

Below that, a card titled `Why the compiler refuses things` with three red
outline buttons and an inline red notice reading:
`internal-knowledge: credentials cannot be exempted — blocking them is not a tunable`

### 3 · Review

Eyebrow: `Where a human is worth interrupting`
Title: `Review`

Three statistic cards: **3** *awaiting a verdict*, **100.0%** *override rate —
the number we look worst on, shown first*, **0** *resolved this session*.

A table: *Item · Profile · Category · Confidence · Why you · Verdict*, with
three small pill buttons per row: `Right to flag`, `False positive`, `Unclear`.

Below, a proposal card: *Profile · Path · Proposed · Because*, with the row
`decision-support · decision.exempt · ["quality:hallucination"] · 3 of 3 reviews
overturned`, and a violet **Recompile and publish** button.

### 4 · Chain

Eyebrow: `The log that cannot be quietly rewritten`
Title: `Chain`

Two buttons: a dark `Verify the chain` and a red-outline `Tamper with entry #0`.
A green result banner, and an alternate red state reading
`✕ chain broken at entry #0`.

Then a vertical list of entry cards. Each shows a sequence number and event
name, a timestamp, two monospace hash lines (`prev` grey, `this` blue), and a
soft-grey JSON block. Entries after a break get a red left edge.

### 5 · Measures

Eyebrow: `The numbers, and what each of them cannot tell you`
Title: `Measures`

- **Canary card**: three statistics — **100.0%** *caught, of 80 seeded*,
  **0.0%** *estimated miss rate*, **95.4% – 100.0%** *95% Wilson interval*. Then
  a small table with thin horizontal progress bars per category (aadhaar 10/10,
  api_key 20/20, iban 10/10, payment_card 40/40). Below it an amber-tinted
  caveat panel.
- **Cost card**: three statistics — baseline, gross saving, net saving — plus a
  monospace summary line.
- **Bias card**: a prominent blue-tinted notice reading *"There is no
  per-response bias score on this page and there never will be."* Then a table
  of counterfactual pairs (`Rajesh Kumar → Rebecca Klein`, outcomes as chips,
  a `diverged` column).
- **Two cards side by side**: `Built · runs after delivery` (green left edge)
  and `Not built · labelled, not omitted` (grey dashed chips).

---

## DO NOT

- Do not use orange or blue for decoration. They mean inside and outside.
- Do not invent statistics. Use the numbers given; they are real output.
- Do not add gradients inside cards, glassmorphism, or neon glows.
- Do not use heavy borders or hard drop shadows.
- Do not centre body text or use all-caps for anything except small labels.
- Do not add a dark mode variant unless asked. This is a light-first design.
- Do not make the charts 3D or add drop shadows to chart elements.

## DELIVER

All five screens at 1600×1000, plus a small token sheet showing the colour
palette, the type scale, the card and pill shapes, and the four state chips
(allow / annotate / review / block).
