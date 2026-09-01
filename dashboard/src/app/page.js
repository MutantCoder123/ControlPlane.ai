'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { get, post, runStream, usd, ms } from '@/lib/api';
import { Marked, Spanned, RawStream } from '@/components/Marked';

const EMPTY = {
  open: null, scan: null, decision: null, dispatch: null,
  raw: '', answer: '', hold: { pending_chars: 0, held_chars: 0 },
  release: null, doneEvent: null, cost: null,
  quality: [], qualityDone: null, block: null, error: null,
  sessionRisk: null,
  events: [],
};

const SESSION_KEY = 'controlplane-session-id';
const mintSessionId = () => crypto.randomUUID().slice(0, 12);

export default function Transit() {
  const [presets, setPresets] = useState([]);
  const [activePreset, setActivePreset] = useState(null);
  const [prompt, setPrompt] = useState('');
  const [profile, setProfile] = useState('internal-knowledge');
  const [profiles, setProfiles] = useState([]);
  const [running, setRunning] = useState(false);
  const [turnLabel, setTurnLabel] = useState(null); // "2 / 4" during a multi-turn preset
  const [sessionId, setSessionId] = useState(null); // set client-side only, after mount
  const [s, setS] = useState(EMPTY);
  const abort = useRef(null);

  useEffect(() => {
    get('/demo/presets')
      .then((d) => {
        setPresets(d.presets);
        if (d.presets[0]) pick(d.presets[0]);
      })
      .catch(() => {});
    get('/demo/profiles').then((d) => setProfiles(d.profiles)).catch(() => {});

    // Session id is generated here, not read from anything the server
    // minted - see orchestrator.py's note on why we never mint one
    // ourselves. Persisted so a page reload continues the same session
    // rather than silently starting a fresh one every time.
    try {
      const existing = window.sessionStorage.getItem(SESSION_KEY);
      const id = existing || mintSessionId();
      if (!existing) window.sessionStorage.setItem(SESSION_KEY, id);
      setSessionId(id);
    } catch {
      setSessionId(mintSessionId()); // storage unavailable - still usable, just not persisted
    }
  }, []);

  const pick = (p) => {
    setActivePreset(p.id);
    setPrompt(p.prompts ? p.prompts[0] : p.prompt);
    if (p.profile) setProfile(p.profile);
  };

  /* One request, narrated - shared by a single send and by each step of a
   * multi-turn preset. Does not reset `sessionRisk`: the server returns the
   * true CUMULATIVE session state on every request, so the previous turn's
   * value is only ever replaced by a fresher one, never cleared early. */
  const runOnce = useCallback((promptText, opts = {}) => {
    const acc = { ...EMPTY, sessionRisk: opts.keepRisk ?? null, events: [] };
    const flush = () => setS({ ...acc, events: [...acc.events] });
    flush();

    return runStream(
      { prompt: promptText, profile, sessionId, agentSteps: opts.agentSteps ?? 0 },
      (e) => {
        acc.events.push(e);
        switch (e.stage) {
          case 'request.open':    acc.open = e; break;
          case 'scan.inbound':    acc.scan = e; break;
          case 'decision':        acc.decision = e; break;
          case 'dispatch':        acc.dispatch = e; break;
          case 'stream.raw':      acc.raw += e.chunk; break;
          case 'buffer.hold':     acc.hold = e; break;
          case 'buffer.release':
            acc.answer += e.text;
            acc.release = e;
            acc.hold = { pending_chars: 0, held_chars: e.held_chars };
            break;
          case 'answer.done':     acc.doneEvent = e; break;
          case 'cost':            acc.cost = e; break;
          case 'quality.finding': acc.quality.push(e); break;
          case 'quality.done':    acc.qualityDone = e; break;
          case 'session.risk':    acc.sessionRisk = e; break;
          case 'block':           acc.block = e; break;
          case 'error':           acc.error = e; break;
          default: break;
        }
        flush();
      },
      abort.current.signal,
    ).then(() => acc.sessionRisk);
  }, [profile, sessionId]);

  const send = useCallback(async () => {
    abort.current?.abort();
    abort.current = new AbortController();
    setRunning(true);
    setTurnLabel(null);
    try {
      await runOnce(prompt, { keepRisk: s.sessionRisk });
    } catch (err) {
      if (err.name !== 'AbortError') {
        setS((prev) => ({ ...prev, error: { reason: `${err.message}. Is the demo server running?` } }));
      }
    } finally {
      setRunning(false);
    }
  }, [prompt, runOnce, s.sessionRisk]);

  /* Fires each prompt in a `prompts` preset in turn, on the same session id,
   * pausing between so the session counter is visibly climbing rather than
   * jumping straight to its final value. No single turn is remarkable; the
   * point is watching the session panel react across all of them. */
  const runSequence = useCallback(async (prompts) => {
    abort.current?.abort();
    abort.current = new AbortController();
    setRunning(true);
    let risk = s.sessionRisk;
    try {
      for (let i = 0; i < prompts.length; i++) {
        setTurnLabel(`${i + 1} / ${prompts.length}`);
        setPrompt(prompts[i]);
        risk = await runOnce(prompts[i], { keepRisk: risk });
        if (i < prompts.length - 1) await new Promise((r) => setTimeout(r, 900));
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setS((prev) => ({ ...prev, error: { reason: `${err.message}. Is the demo server running?` } }));
      }
    } finally {
      setRunning(false);
    }
  }, [runOnce, s.sessionRisk]);

  const newSession = useCallback(async () => {
    if (sessionId) {
      try { await post(`/demo/session/${sessionId}/forget`, {}); } catch { /* fine either way */ }
    }
    const fresh = mintSessionId();
    try { window.sessionStorage.setItem(SESSION_KEY, fresh); } catch { /* ignore */ }
    setSessionId(fresh);
    setS((prev) => ({ ...prev, sessionRisk: null }));
  }, [sessionId]);

  const mapping = s.scan?.mapping ?? {};
  const placeholders = Object.keys(mapping);
  const realValues = Object.values(mapping);
  const preset = presets.find((p) => p.id === activePreset);
  const blocked = Boolean(s.block);
  const heldChars = (s.hold?.pending_chars ?? 0) + (s.hold?.held_chars ?? 0);

  const boundaryState = blocked
    ? 'blocked'
    : running && s.dispatch
    ? 'crossing'
    : 'idle';

  return (
    <>
      <span className="eyebrow">Watch one request cross the line</span>
      <h1 className="title">Transit</h1>
      <p className="lede">
        Everything on this page was computed by a module in this repository, during this run.
        The left half is <strong>inside the building</strong>. The right half is what the model
        provider actually received. Real values are warm and never render on the right;
        placeholders are cold and are the only thing that crosses.
      </p>

      <div className="presets">
        {presets.map((p) => (
          <button
            key={p.id}
            className="preset"
            data-active={activePreset === p.id}
            onClick={() => pick(p)}
            disabled={running}
          >
            <b>{p.title}</b>
            <span>{p.proves}</span>
          </button>
        ))}
      </div>

      <div className="composer">
        <textarea
          value={prompt}
          onChange={(e) => { setPrompt(e.target.value); setActivePreset(null); }}
          disabled={running}
          placeholder="Paste anything. Try a real customer record."
          spellCheck={false}
        />
        <div className="composer-row">
          <select value={profile} onChange={(e) => setProfile(e.target.value)} disabled={running}>
            {profiles.map((p) => (
              <option key={p.name} value={p.name}>{p.name}</option>
            ))}
          </select>
          {preset?.prompts ? (
            <button
              className="btn btn-primary"
              onClick={() => runSequence(preset.prompts)}
              disabled={running}
            >
              {running ? `Turn ${turnLabel}…` : `Run ${preset.prompts.length} turns`}
            </button>
          ) : (
            <button className="btn btn-primary" onClick={send} disabled={running || !prompt.trim()}>
              {running ? 'In flight…' : 'Send request'}
            </button>
          )}
          {s.open && (
            <span className="chip mono">
              fp {s.open.fingerprint} · policy v{s.open.policy_version}
            </span>
          )}
          {s.open && (
            <span className="chip mono">
              {s.open.streaming.mode} · commit at {s.open.streaming.commit_tokens} tok /
              {' '}{s.open.streaming.commit_ms}ms · hold {s.open.streaming.overlap_chars} chars
            </span>
          )}
        </div>
        {preset && <div className="note" style={{ marginTop: 10 }}><b>Watch for:</b> {preset.watch}</div>}
      </div>

      {s.error && (
        <div className="note" data-kind="stop" style={{ marginBottom: 16 }}>
          <b>{s.error.reason}</b>
          {s.error.hint && <div style={{ marginTop: 4 }}>{s.error.hint}</div>}
        </div>
      )}

      {/* ---------------------------------------------------------- stage -- */}
      <div className="stage">
        <div className="side-label side-in">
          <span className="eyebrow" data-side="inside">Inside the building</span>
          <span className="chip mono">your data never leaves this column</span>
        </div>

        <div className="boundary" data-state={boundaryState}>
          <span className="boundary-label">
            {blocked ? 'stopped here' : 'provider boundary'}
          </span>
        </div>

        <div className="side-label side-out">
          <span className="eyebrow" data-side="outside">Outside · the model provider</span>
          {s.dispatch && (
            <span className="check" data-ok={s.dispatch.leak_check.ok}>
              {s.dispatch.leak_check.ok ? '✓' : '✕'} leak check ·{' '}
              {s.dispatch.leak_check.leaked.length} of {s.dispatch.leak_check.checked} real values present
            </span>
          )}
        </div>

        {/* ① what you sent */}
        <div className="quad q1">
          <div className="quad-title"><i>01</i> What you sent</div>
          <p className="payload">
            {s.scan ? <Spanned text={s.scan.original} findings={s.scan.findings} /> : (prompt || null)}
          </p>
          {s.scan && (
            <div className="findings">
              {s.scan.findings.length === 0 && (
                <div className="check">nothing matched — no record, no checksum, no credential</div>
              )}
              {s.scan.findings.map((f, i) => (
                <div className="finding" key={i} data-action={f.action}>
                  <span className="cat">{f.category}</span>
                  <span className="why">
                    {f.record_ref
                      ? `matched ${f.record_ref}`
                      : `${f.kind} tier — no record reference (D28)`}
                    {f.action === 'block' && ' · cannot be substituted, so it stops here'}
                  </span>
                  <span className="conf">{f.confidence.toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ② what the provider received */}
        <div className="quad q2">
          <div className="quad-title"><i>02</i> What the provider received</div>
          {blocked && s.block.where === 'inbound' ? (
            <>
              <p className="payload" style={{ color: 'var(--text-faint)' }}>
                nothing — the request was never dispatched
              </p>
              <div className="note" data-kind="stop">
                <b>{s.block.reason}</b>
                <div style={{ marginTop: 6 }}>
                  Refused before dispatch, so it cost {usd(s.block.cost_usd, 2)}. You are billed the
                  moment tokens are generated — forwarding first and cancelling on failure would have
                  blocked the request <i>and</i> paid for it.
                </div>
              </div>
            </>
          ) : s.dispatch ? (
            <p className="payload">
              <Marked
                text={s.dispatch.text}
                needles={placeholders}
                className="tok-ph"
                title={(p) => `${p} — the provider is told only that this is one consistent entity`}
              />
            </p>
          ) : (
            <p className="payload-empty">waiting for the inbound scan…</p>
          )}
        </div>

        {/* ③ what the model wrote */}
        <div className="quad q3">
          <div className="quad-title">
            <i>03</i> What the model wrote
            {s.release && (
              <span className="chip mono" style={{ marginLeft: 'auto' }}>
                commit {s.release.commits} · {s.release.trigger}
              </span>
            )}
          </div>
          {s.raw ? (
            <p className="payload">
              <RawStream text={s.raw} placeholders={placeholders} heldChars={heldChars} />
              {running && <span className="caret" />}
            </p>
          ) : (
            <p className="payload-empty">
              {running ? 'model is thinking…' : 'the raw stream appears here, placeholders intact'}
            </p>
          )}
          {heldChars > 0 && running && (
            <div className="check" style={{ color: 'var(--held)' }}>
              holding {heldChars} chars — not released until it has been scanned as one piece
              with what follows
            </div>
          )}
        </div>

        {/* ④ what you read */}
        <div className="quad q4">
          <div className="quad-title">
            <i>04</i> What you read
            {s.doneEvent && (
              <span className="chip mono" style={{ marginLeft: 'auto' }}>
                ttfb {ms(s.doneEvent.ttfb_ms)} · {s.doneEvent.commits} commits
              </span>
            )}
          </div>
          {blocked && s.block.where === 'outbound' ? (
            <div className="note" data-kind="stop">
              <b>Stream stopped: {s.block.reason}</b>
              <div style={{ marginTop: 6 }}>
                The half-sentence carrying it was never released. Once a token reaches the browser
                it is in the DOM and in the stream — a kill switch after render is theatre.
              </div>
            </div>
          ) : s.answer ? (
            <p className="payload">
              <Marked text={s.answer} needles={realValues} className="tok-real" fresh title="restored on the way out" />
              {running && <span className="caret" />}
            </p>
          ) : (
            <p className="payload-empty">
              {running ? 'buffering to the first commit point…' : 'the restored answer appears here'}
            </p>
          )}
          {s.doneEvent && (
            <div className="check" data-ok={s.doneEvent.unrestored.length === 0}>
              {s.doneEvent.unrestored.length === 0
                ? `✓ ${s.doneEvent.restored} values restored · 0 unrestored`
                : `✕ ${s.doneEvent.unrestored.length} placeholders survived: ${s.doneEvent.unrestored.join(', ')}`}
            </div>
          )}
        </div>
      </div>

      {/* -------------------------------------------------- after delivery -- */}
      <div className="cols cols-4" style={{ marginTop: 16 }}>
        <section className="panel" data-role="session">
          <div className="panel-head">
            <span className="panel-title">This session</span>
            <span className="chip mono">{sessionId ?? '—'}</span>
          </div>
          <div className="panel-body">
            {s.sessionRisk ? (
              <>
                <div className="cols cols-2" style={{ marginBottom: 10, rowGap: 10 }}>
                  <div className="stat">
                    <span className="v">{s.sessionRisk.turns}</span>
                    <span className="k">turns</span>
                  </div>
                  <div className="stat" data-tone={s.sessionRisk.over_budget ? 'stop' : undefined}>
                    <span className="v">
                      {s.sessionRisk.distinct_records} / {s.sessionRisk.limits.max_records_per_session}
                    </span>
                    <span className="k">records touched</span>
                  </div>
                  <div className="stat">
                    <span className="v">{s.sessionRisk.agent_steps}</span>
                    <span className="k">agent steps</span>
                  </div>
                  <div className="stat">
                    <span className="v">{s.sessionRisk.blocks}</span>
                    <span className="k">blocks</span>
                  </div>
                </div>
                {s.sessionRisk.over_budget && (
                  <div className="note" data-kind="stop" style={{ marginBottom: 10 }}>
                    {s.sessionRisk.reasons.map((r, i) => <div key={i}>⚠ {r}</div>)}
                  </div>
                )}
              </>
            ) : (
              <p className="payload-empty">no turns yet this session</p>
            )}
            <div className="hash prose">counters only — no prompt, no response, no value</div>
            <div className="composer-row" style={{ marginTop: 10 }}>
              <button className="btn" onClick={newSession} disabled={running}>New session</button>
            </div>
          </div>
        </section>

        <section className="panel" data-role="decision">
          <div className="panel-head">
            <span className="panel-title">Decision</span>
            {s.decision && <span className="chip" data-tier={s.decision.tier}>{s.decision.tier}</span>}
          </div>
          <div className="panel-body">
            {s.decision ? (
              <div className="findings">
                {s.decision.outcomes.length === 0 && (
                  <div className="check">no signals — nothing to decide</div>
                )}
                {s.decision.outcomes.map((o, i) => (
                  <div className="finding" key={i} data-action={o.mitigated ? 'substitute' : 'block'}>
                    <span className="cat">{o.category}</span>
                    <span className="why">{o.reason}</span>
                    <span className="chip" data-tier={o.tier}>{o.tier}</span>
                  </div>
                ))}
                {s.decision.escalations.length > 0 && (
                  <div className="note" data-kind="cold">
                    Escalated to a human: {s.decision.escalations.join(', ')}
                  </div>
                )}
                <div className="note">
                  The tier is a function of severity × confidence × <b>profile</b>, never the
                  finding alone. Substitution counts as mitigation — the finding is still recorded,
                  it just no longer has anything to prevent.
                </div>
              </div>
            ) : (
              <p className="payload-empty">waiting…</p>
            )}
          </div>
        </section>

        <section className="panel" data-role="after-delivery">
          <div className="panel-head">
            <span className="panel-title">After delivery · reversible harms</span>
            {s.qualityDone && <span className="chip mono">{s.quality.length} finding(s)</span>}
          </div>
          <div className="panel-body">
            {s.quality.length === 0 && !s.qualityDone && (
              <p className="payload-empty">
                these run <em>after</em> the answer is delivered — that is the point
              </p>
            )}
            {s.quality.map((q, i) => (
              <div className="note" key={i} style={{ marginBottom: 8 }}>
                <b>{q.check}</b> <span className="chip" data-tier={q.tier}>{q.tier}</span>
                <div style={{ marginTop: 5 }}>{q.evidence}</div>
                <div className="hash prose" style={{ marginTop: 5 }}>
                  confidence {q.confidence} = {q.confidence_formula}
                </div>
                {s.doneEvent && (
                  <div className="hash" style={{ marginTop: 3 }}>
                    arrived {Math.round(q.t_ms - s.doneEvent.t_ms)}ms after the reader had the answer
                  </div>
                )}
              </div>
            ))}
            {s.qualityDone?.skipped && (
              <div className="check">skipped — {s.qualityDone.skipped}</div>
            )}
            {s.qualityDone?.not_built && (
              <div className="note" data-kind="cold" style={{ marginTop: 8 }}>
                <b>Not built, deliberately.</b>
                {Object.entries(s.qualityDone.not_built).map(([k, v]) => (
                  <div key={k} style={{ marginTop: 5 }}>
                    <span className="chip" data-kind="off">{k}</span> {v}
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="panel" data-role="cost">
          <div className="panel-head"><span className="panel-title">Cost of this request</span></div>
          <div className="panel-body">
            {s.cost ? (
              <>
                <div className="cols cols-2" style={{ marginBottom: 12 }}>
                  <div className="stat" data-tone="ok">
                    <span className="v">{usd(s.cost.request_usd, 5)}</span>
                    <span className="k">what we paid, routed</span>
                  </div>
                  <div className="stat" data-tone="warm">
                    <span className="v">{usd(s.cost.baseline_usd, 5)}</span>
                    <span className="k">baseline · {s.cost.baseline_model}</span>
                  </div>
                </div>
                <div className="note">
                  {s.cost.note}. Served by {s.cost.served_by}, priced against{' '}
                  <b>{s.cost.model}</b>.
                </div>
                {s.cost.running_total && (
                  <div className="hash prose" style={{ marginTop: 8 }}>
                    session net saving {usd(s.cost.running_total.net_saving_usd, 5)} across{' '}
                    {s.cost.running_total.requests} request(s) — gross minus our own overhead,
                    because the flattering number should not be readable alone
                  </div>
                )}
              </>
            ) : blocked ? (
              <div className="stat" data-tone="stop">
                <span className="v">{usd(0, 2)}</span>
                <span className="k">refused before dispatch — nothing was generated</span>
              </div>
            ) : (
              <p className="payload-empty">waiting…</p>
            )}
          </div>
        </section>
      </div>

      {/* ----------------------------------------------------------- tape -- */}
      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <span className="panel-title">The tape · every event, in order</span>
          <span className="chip mono">{s.events.length} events</span>
        </div>
        <div className="tape">
          {s.events.length === 0 && (
            <div className="panel-body">
              <p className="payload-empty">
                nothing on screen comes from anywhere but this list
              </p>
            </div>
          )}
          {s.events.map((e) => (
            <div className="tape-row" key={e.seq} data-side={e.side} data-stage={e.stage}>
              <span className="t">{e.t_ms.toFixed(0)}</span>
              <span className="sq">#{e.seq}</span>
              <span className="st">{e.stage}</span>
              <span className="dt">{describe(e)}</span>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

function describe(e) {
  switch (e.stage) {
    case 'request.open':
      return `${e.profile} · fp ${e.fingerprint} · served by ${e.served_by}`;
    case 'scan.inbound':
      return `${e.findings.length} finding(s) in ${e.scan_ms}ms${e.blocked ? ` · ${e.block_reason}` : ''}`;
    case 'decision':
      return `${e.tier} · ${e.outcomes.map((o) => `${o.category}:${o.reason}`).join(' · ') || 'no signals'}`;
    case 'dispatch':
      return `${e.input_tokens} tokens · leak check ${e.leak_check.ok ? 'passed' : 'FAILED'}`;
    case 'stream.raw':
      return JSON.stringify(e.chunk);
    case 'buffer.hold':
      return `pending ${e.pending_chars} · held ${e.held_chars} · ${e.why}`;
    case 'buffer.release':
      return `${e.trigger} · released ${e.text.length} chars · still holding ${e.held_chars}`;
    case 'answer.done':
      return `${e.restored} restored · ${e.unrestored.length} unrestored · ttfb ${ms(e.ttfb_ms)}`;
    case 'audit.append':
      return `#${e.entry.seq} ${e.entry.event} · ${e.entry.entry_hash.slice(0, 16)}…`;
    case 'block':
      return `${e.where} · ${e.reason} · ${usd(e.cost_usd, 4)}`;
    case 'cost':
      return `${usd(e.request_usd, 5)} vs baseline ${usd(e.baseline_usd, 5)}`;
    case 'quality.finding':
      return `${e.check} · ${e.confidence} · ${e.evidence}`;
    case 'quality.done':
      return e.skipped ?? `ran ${e.ran.join(', ') || 'nothing'}`;
    case 'queue.enqueue':
      return `${e.item_id} · ${e.category} · ${e.reason}`;
    case 'error':
      return e.reason;
    case 'done':
      return e.outcome;
    default:
      return '';
  }
}
