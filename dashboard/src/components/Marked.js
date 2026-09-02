'use client';

/* Highlighting without guessing at the placeholder format.
 *
 * CONTRACTS section 4: Track A owns the placeholder format and may change it,
 * which is exactly why nothing outside the engine may hardcode it. The build
 * this replaces split on /(\[\[[A-Z_]+\]\])/ - already wrong, because the
 * engine's own pattern allows digits, so the 27th customer in a request
 * becomes [[CUST_A2]] and the highlighting silently stops.
 *
 * So we never pattern-match. We split on the exact literal strings the engine
 * minted and sent us: the keys of `mapping` for placeholders, its values for
 * real ones. If the format changes tomorrow, this keeps working.
 */

const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function splitter(needles) {
  const live = needles.filter(Boolean).sort((a, b) => b.length - a.length);
  if (!live.length) return null;
  return new RegExp(`(${live.map(escape).join('|')})`, 'g');
}

/** Text with the literal `needles` wrapped in `className`. */
export function Marked({ text, needles, className, title, fresh }) {
  const re = splitter(needles ?? []);
  if (!text) return null;
  if (!re) return <>{text}</>;

  const set = new Set(needles.filter(Boolean));
  return (
    <>
      {text.split(re).map((part, i) =>
        set.has(part) ? (
          <span
            key={i}
            className={className}
            data-fresh={fresh ? 'true' : undefined}
            title={typeof title === 'function' ? title(part) : title}
          >
            {part}
          </span>
        ) : (
          part
        ),
      )}
    </>
  );
}

/** The prompt, with each finding's exact span underlined.
 *
 * Spans are the engine's, measured against the original text - which is why
 * `Finding.span` is on the wire at all. Two findings never overlap, because
 * `_reconcile` already resolved that server-side.
 */
export function Spanned({ text, findings }) {
  if (!text) return null;
  if (!findings?.length) return <>{text}</>;

  const ordered = [...findings].sort((a, b) => a.span[0] - b.span[0]);
  const out = [];
  let at = 0;

  ordered.forEach((f, i) => {
    const [start, end] = f.span;
    if (start < at) return;
    if (start > at) out.push(text.slice(at, start));
    out.push(
      <span
        key={i}
        className={f.action === 'block' ? 'tok-stop' : 'tok-real'}
        title={`${f.kind} · ${f.category} · confidence ${f.confidence.toFixed(2)}${
          f.record_ref ? ` · ${f.record_ref}` : ' · no record (pattern tier)'
        }`}
      >
        {text.slice(start, end)}
      </span>,
    );
    at = end;
  });

  if (at < text.length) out.push(text.slice(at));
  return <>{out}</>;
}

/** The delivered answer, with hallucination/overclaim findings (D33)
 * highlighted exactly where they sit - confidence shown inline as a small
 * badge, not hidden behind a hover, plus the full evidence in the tooltip
 * for anyone who wants it.
 *
 * Composes with `Marked`'s real-value highlighting rather than replacing
 * it: a quality finding flags text the model actually typed, which by
 * construction is never a restored placeholder value (a hallucinated
 * entity has no substitution mapping - nothing to restore), so the two
 * kinds of span never overlap. This walks the quality findings first, then
 * re-applies `Marked` to whatever plain text falls between them, so real
 * values still warm-flash exactly as they did before this feature existed.
 *
 * Findings without a `span` (toxicity describes the whole reply, not one
 * substring) are simply skipped here - they still show up in the findings
 * list below, this only handles the ones with something to underline.
 */
export function AnnotatedAnswer({ text, findings, realValueNeedles, fresh }) {
  if (!text) return null;
  const spanned = (findings ?? []).filter((f) => f.span);
  const plain = (slice, key) => (
    <Marked key={key} text={slice} needles={realValueNeedles}
            className="tok-real" fresh title="restored on the way out" />
  );
  if (!spanned.length) return plain(text, 'all');

  const ordered = [...spanned].sort((a, b) => a.span[0] - b.span[0]);
  const out = [];
  let at = 0;

  ordered.forEach((f, i) => {
    const [start, end] = f.span;
    if (start < at) return; // overlapping with an earlier finding - keep that one
    if (start > at) out.push(plain(text.slice(at, start), `gap-${i}`));
    out.push(
      <mark
        key={i}
        className={`halluc-mark cat-${f.category}`}
        title={`${f.check} · ${f.evidence} · confidence ${f.confidence.toFixed(2)}`}
      >
        {text.slice(start, end)}
        <sup className="halluc-badge">{Math.round(f.confidence * 100)}%</sup>
      </mark>,
    );
    at = end;
  });

  if (at < text.length) out.push(plain(text.slice(at), 'tail'));
  return <>{out}</>;
}

/** Raw model output: placeholders cold, the not-yet-released tail amber.
 *
 * `heldChars` comes from the buffer itself (`pending_chars + held_chars`), so
 * the amber region is literally what P4 is holding back, not an approximation
 * drawn by the browser.
 */
export function RawStream({ text, placeholders, heldChars = 0 }) {
  if (!text) return null;
  const cut = Math.max(0, text.length - heldChars);
  const released = text.slice(0, cut);
  const held = text.slice(cut);

  return (
    <>
      <Marked text={released} needles={placeholders} className="tok-ph" />
      {held && (
        <span className="tok-held" title="held by the commit-point buffer — scanned as one piece with what follows (D5)">
          {held}
        </span>
      )}
    </>
  );
}
