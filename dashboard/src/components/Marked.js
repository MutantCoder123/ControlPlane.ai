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
