# Implementing the light theme

**Source:** `controlplane-screens-built/project/` — `ControlPlane.dc.html` (5
screens + token sheet), `IconRail.dc.html`, `support.js`.
**Status:** plan · 2026-08-30 · supersedes the speculative version of this file.

`support.js` is the Claude Design runtime (`x-dc`, `sc-for`, `dc-import`,
`DCLogic`). None of it ports — it is the prototype's templating layer, and React
already does that job. What ports is the CSS and the layout.

---

## 1 · The token system, extracted

Read off the design directly. No interpretation.

```css
:root {
  /* ground */
  --backdrop:      #DCDFE6;   /* behind the app frame */
  --ground:        #F1F3F7;   /* the app surface */
  --bench:         #FFFFFF;   /* cards */
  --bench-raised:  #F1F3F7;   /* insets, JSON blocks, chip fills */
  --rule:          #E7EAF0;

  /* type */
  --text:          #111318;
  --text-dim:      #3F4552;
  --text-faint:    #8A91A0;

  /* semantic — see the contrast fix in section 4 */
  --inside-mark:   #F97316;   --inside-glow:  #FFF1E6;
  --outside-mark:  #2563EB;   --outside-glow: #E8EFFD;
  --held:          #F59E0B;   --held-glow:    #FEF3C7;
  --stop:          #DC2626;   --stop-glow:    #FEE9E9;
  --ok:            #16A34A;   --ok-glow:      #E7F6EC;
  --violet:        #7C3AED;
  --sky:           #38BDF8;

  /* shape — a scale, not one value */
  --r-frame: 28px;  --r-card: 24px;  --r-panel: 20px;
  --r-input: 16px;  --r-note: 14px;  --r-inset: 10px;  --r-pill: 999px;

  --shadow:       0 2px 20px rgba(17, 19, 24, 0.05);
  --shadow-frame: 0 24px 70px rgba(17, 19, 24, 0.14);

  --rail: 80px;
}
```

**Fonts — three, not one.** I was wrong in the earlier draft; the design does
pair. Page titles are **Outfit** 700; everything else is **Plus Jakarta Sans**;
wire content is **JetBrains Mono**. Outfit appears only on the five 52px page
titles, which is enough of a job to justify it.

**Type scale:** page title `52/700/-0.02em` (Outfit) · eyebrow `15` muted ·
card title `16/700` · section title `18/700` · body `13–15` · label `11–12/700`
uppercase `.03em` · stat `40/700` · mono stat `22–26/700` · payload mono `14/1.7`.

**Cards are tinted by role, not all white.** This is the biggest thing I got
wrong in the earlier draft:

| Card | Tint |
|---|---|
| Decision | `rgba(22,163,74,.13)` |
| After delivery | `rgba(245,158,11,.13)` |
| Cost | `rgba(56,189,248,.13)` |
| Profile cards | `rgba(<accent>,.06)` |
| Review stats | `rgba(<accent>,.07–.08)` |
| Chain entries | `rgba(<accent>,.06)` + 4px left edge |
| Everything else | `#FFFFFF` |

---

## 2 · Where the design and the running system disagree

**The design's data is placeholder. Ours is real. Keep ours — every time.**

This is the single most important section of this document. The pitch's whole
claim is *"every number on screen was computed during this run."* Hard-coding
the design's sample values would break that claim on camera, and the repo is
public, so a judge can check.

### The profile numbers are inverted

| Profile | Design says | **Actually** |
|---|---|---|
| `customer-support` | blocks at 0.85, budget 12 | **0.75**, band 0.35–0.75, budget **5** |
| `decision-support` | blocks at 0.75, budget 5 | **0.85**, band 0.40–0.85, budget **100**, reviews everything |
| `internal-knowledge` | blocks at 0.65 — *"strictest"* | **0.90**, band 0.50–0.90, budget **10** |

The design has it backwards, and the inversion matters: **public-facing output
justifies stopping earlier than an internal assistant does.** That sentence is
in the pitch. Rendering internal-knowledge as the strictest route contradicts
the argument the screen exists to make.

The values come from `GET /demo/profiles`. Do not hard-code any of them.

### Other drift, same rule

| Design | Reality | Action |
|---|---|---|
| Currency `₹0.0365` | `CostLedger` prices in **USD** from published rates | **Keep `$`.** A rupee figure needs an FX rate we do not have, and inventing one is exactly the fabrication this dashboard refuses |
| Tape stages `substitute`, `forward.provider`, `leak_check`, `deliver` | `scan.inbound`, `dispatch`, `buffer.release`, `answer.done`, `cost`, `quality.finding` | **Keep the real event names.** The tape's only job is traceability |
| *"The landmine — a finding that only exists after the model answers"* | The landmine is Luhn-valid-but-not-ours; known-value beats regex | **Keep the server's copy** from `GET /demo/presets` |
| *"The edge of governance — confidence 0.35–0.75"* | It is about ungoverned data sources (D28), not confidence | Same — server copy |
| Review items `req_88213` | `4f29e5611012-1` | Real ids |
| Chain events `review.overturn`, `canary.sample` | `scan`, `policy_change` | Real events |
| Bias pairs `Fatima Al-Sayed → Fiona Adler` | Whatever `POST /demo/bias` returns | Real output |

**Rule for the whole port: the design supplies the styling; the API supplies
every string and number.** Where the design shows content we do not produce,
either wire it to something real or cut it (section 5).

---

## 3 · File-by-file

The five pages still barely change — the class names stay, so this remains a
CSS job plus one new component.

| File | Change |
|---|---|
| `src/app/globals.css` | token block + component rules — the bulk |
| `src/app/layout.js` | Outfit + Plus Jakarta Sans + JetBrains Mono; wrap in the frame |
| `src/components/Rail.js` | **new** — port from `IconRail.dc.html` |
| `src/components/Nav.js` | reduce to eyebrow + title + health pill |
| `src/app/*/page.js` | add an `eyebrow` line above each `h1.title`; a handful of class swaps |
| `src/components/Marked.js` | unchanged |

### The rail — port directly

`IconRail.dc.html` is complete and correct. 80px column, 44px circles, 14px gap,
`padding: 20px 0`. Logo is a 44px `#111318` circle with a ring-and-dot SVG.
Active item: `background #111318`, `border #111318`, icon `#FFFFFF`. Inactive:
`background #FFFFFF`, `border #E7EAF0`, icon `#3F4552`. A `flex:1` spacer, then
a settings circle pinned to the bottom.

The five icons are inline SVG in the design's `renderVals()` — lift them
verbatim, replacing the `COLOR` sentinel with a prop. Order is fixed and matches
the demo: **transit · profiles · review · chain · measures**.

### The frame

```css
body   { background: var(--backdrop); }
.frame { background: var(--ground); border-radius: var(--r-frame);
         box-shadow: var(--shadow-frame); padding: 28px; display: flex; }
.shell { flex: 1; padding-left: 28px; min-width: 0;
         display: flex; flex-direction: column; gap: 22px; }
```

Below ~1700px the floating frame wastes space — drop `--shadow-frame` and the
radius, and let it go full-bleed.

### The boundary

The design replaces the hatch with a **22px vertical gradient spine**, centred,
with `CONTROLPLANE` in vertical violet 10px letters over it:

```css
.boundary {
  position: absolute; left: 50%; top: 0; bottom: 0;
  width: 22px; transform: translateX(-50%); z-index: 1;
  background: linear-gradient(180deg,
    rgba(249,115,22,.14), rgba(124,58,237,.10) 50%, rgba(37,99,235,.14));
}
```

This is better than the hatch on light — softer, and the warm→cool gradient
echoes the temperature rule.

**One caveat.** The gradient runs orange **top** → blue **bottom**, but the
semantic axis is left/right. A viewer could read the vertical fade as encoding
something it doesn't. The column headers (`INSIDE THE BUILDING` orange left,
`OUTSIDE` blue right) carry the real meaning, so it reads fine — but if it ever
confuses someone in rehearsal, switch to `90deg` and let the gradient run across
the spine instead of down it.

Note the stage becomes `position: relative` with the spine absolutely
positioned, rather than a grid column. The `.q1`–`.q4` explicit placement is
replaced by two `grid-template-columns: 1fr 1fr` rows, with `order: 2` / `order:
1` on the bottom row to put **04 left, 03 right**. Same clockwise circuit.

### The canary donuts — adopt these

Better than our progress bars, and no library:

```css
.donut {
  width: 36px; height: 36px; border-radius: 50%;
  background: conic-gradient(var(--ok) 0deg var(--deg), var(--rule) var(--deg) 360deg);
  mask: radial-gradient(farthest-side, transparent calc(100% - 6px), #000 calc(100% - 6px));
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 6px), #000 calc(100% - 6px));
}
```

Set `--deg` inline from `caught / seeded * 360`. Four-up grid, `border-right`
hairline between.

---

## 4 · The contrast fix — do not skip this

The design uses `#F97316` text on `#FFF1E6`, and `#2563EB` on `#E8EFFD`. I
computed both:

| Pair | Ratio | AA (4.5:1) |
|---|---|---|
| `#F97316` on `#FFF1E6` | **2.53:1** | ✕ fails badly |
| `#2563EB` on `#E8EFFD` | **4.44:1** | ✕ marginal fail |
| `#C2410C` on `#FFF1E6` | **4.68:1** | ✓ |
| `#1D4ED8` on `#E8EFFD` | **5.77:1** | ✓ |

So split each side into a text colour and a mark colour:

```css
--inside:  #C2410C;   --inside-mark:  #F97316;   /* mark = dots, borders, gradient */
--outside: #1D4ED8;   --outside-mark: #2563EB;
```

Placeholder chips are the most-looked-at text on the busiest screen, and that
screen is going on a projector in a lit room. The colour still reads as orange
and blue; nothing about the semantic rule changes. Keep the saturated values for
the finding dots, the chip borders, the gradient spine and the diff `NOW`
column, where contrast minimums don't apply.

---

## 5 · What to cut, and what to add

### Cut — the design draws controls we have no backend for

- **The `Live / Audit` segmented pill** (Transit header) — there is no such mode.
- **The search field** — nothing to search. If it's wanted visually, wire it to
  filter the tape; otherwise remove it. A search box that does nothing is D23
  in the UI.
- **`Disable canary sampling` / `Skip the review band`** (Profiles) — the real
  refusals are `block_credentials: false`, `exempt: ["pattern:api_key"]`, and an
  unknown key. Use those three; each returns a real `PolicyError`.
- **`Intent classification` / `Real-time human review queue`** in the *Not
  built* chips — we **do** have a review queue, and intent classification was
  never on the roadmap. The real list is `toxicity` and `consistency_sampling`,
  from `GET /demo/quality/status`.

### Add — states the design doesn't draw

The design is five static screens. The live UI needs the states around them,
each already implemented and each needing a light-theme treatment:

- streaming caret · held text in `--held` with a dotted underline · the
  `holding N chars` caption
- the **blocked** stage: spine turns `--stop`, right column empty, `$0.00`
- `✕ N placeholders survived` (the D15 alarm, failure state)
- `✕ chain broken at entry #0` + red left edge on every entry from there
- empty states — the tape before a run, the queue when empty
- the `error` note when the demo server or model is unreachable

---

## 6 · Order of work

| # | Step | Verify |
|---|---|---|
| 1 | Token block, fonts, delete the dark grid overlay | pages render |
| 2 | `.frame` + `.shell`, `Rail.js`, trim `Nav.js`, eyebrows on all five | rail highlights the right page |
| 3 | Cards: radius scale, shadow, role tints, padding pass | white-on-grey with soft shadow |
| 4 | The stage: spine, two rows, `order` swap, column headers | round trip renders as a circuit |
| 5 | **`.tok-real` / `.tok-ph` with the section-4 colours** | **contrast check — `npx @axe-core/cli`** |
| 6 | Pills, buttons, chips, stat cards, state chips | `/policy`, `/queue` |
| 7 | Tape, `pre.dump`, chain entry tints + left edges | `/verify` JSON legible |
| 8 | Canary donuts, cost + bias panels | `/trust` |
| 9 | The dynamic states in section 5 | run all five presets, then tamper |
| 10 | Screenshot all five, diff against the design | — |

Steps 1 and 3–8 are pure CSS. Step 2 is the only structural JSX work; step 9 is
mostly re-theming rules that already exist.

---

## 7 · Before any of this

Two things outrank the reskin:

1. **The restore bug.** `[[CUST_A]]` renders unrestored in quadrant 04 when a
   placeholder straddles the buffer's release boundary, and `answer.done`
   reports `0 unrestored` because it measures the raw text rather than the
   assembled answer. It is visible in beat 1 of the video. A new theme on a
   broken round trip is worse than an old theme on a working one.
2. **Track B's PR.** Merging after the reskin means resolving their gateway work
   against a rewritten `globals.css` for no reason. Merge first.
