'use client';

import { useEffect, useState } from 'react';
import { get, post, usd, pct } from '@/lib/api';

/* Demo step 8 — the numbers, with their caveats attached.
 *
 * The asymmetry this page exists to be honest about: false positives are
 * MEASURED (we see every flag), false negatives are ESTIMATED (we cannot count
 * what we missed). Seeded canaries give the estimate a method and a
 * confidence interval, and the caveat travels with the number because the
 * report enforces it. A catch rate quoted alone is a claim about the
 * categories we happened to seed.
 */
export default function Measures() {
  const [canary, setCanary] = useState(null);
  const [cost, setCost] = useState(null);
  const [quality, setQuality] = useState(null);
  const [bias, setBias] = useState(null);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    get('/demo/cost').then(setCost).catch(() => {});
    get('/demo/quality/status').then(setQuality).catch((e) => setErr(e.message));
  }, []);

  const run = async (what, fn, set) => {
    setBusy(what); setErr(null);
    try { set(await fn()); } catch (e) { setErr(e.message); } finally { setBusy(null); }
  };

  return (
    <>
      <span className="eyebrow">The numbers, and what each of them cannot tell you</span>
      <h1 className="title">Measures</h1>
      <p className="lede">
        False positives we measure — we see every flag we raise. False negatives we{' '}
        <strong>estimate</strong>, because nobody can count what they did not detect. Planting
        canaries and counting how many come back is the honest version of that, and the caveat is
        part of the number rather than a footnote.
      </p>

      {err && <div className="note" data-kind="stop" style={{ marginBottom: 16 }}>{err}</div>}

      {/* ------------------------------------------------------- canaries -- */}
      <section className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-head">
          <span className="panel-title">False-negative estimate · seeded canaries</span>
          <button className="btn" disabled={busy === 'canary'}
            onClick={() => run('canary', () => post('/demo/canary', {}), setCanary)}>
            {busy === 'canary' ? 'Sweeping…' : 'Run a sweep now'}
          </button>
        </div>
        <div className="panel-body">
          {!canary ? (
            <p className="payload-empty">
              Mints synthetic secrets, plants them, and counts how many the detector returns.
              Nothing is precomputed — the sweep runs against the same engine the Transit page just used.
            </p>
          ) : (
            <>
              <div className="cols cols-3" style={{ marginBottom: 14 }}>
                <div className="stat" data-tone="ok">
                  <span className="v">{pct(canary.catch_rate)}</span>
                  <span className="k">caught, of {canary.canaries_seeded} seeded</span>
                </div>
                <div className="stat" data-tone="warm">
                  <span className="v">{pct(canary.estimated_miss_rate)}</span>
                  <span className="k">estimated miss rate</span>
                </div>
                <div className="stat" data-tone="cold">
                  <span className="v" style={{ fontSize: 19 }}>
                    {pct(canary.confidence_interval_95[0])} – {pct(canary.confidence_interval_95[1])}
                  </span>
                  <span className="k">95% Wilson interval — 80 samples is a small n and the interval says so</span>
                </div>
              </div>

              <div style={{
                display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                border: '1px solid var(--rule)', borderRadius: 'var(--r-inset)',
                marginBottom: 12, overflow: 'hidden',
              }}>
                {Object.entries(canary.by_category).map(([cat, ratio], i, arr) => {
                  const [c, t] = ratio.split('/').map(Number);
                  return (
                    <div key={cat} style={{
                      display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px',
                      borderRight: i < arr.length - 1 ? '1px solid var(--rule)' : 'none',
                    }}>
                      <div className="donut" style={{ '--deg': `${t ? (c / t) * 360 : 0}deg` }} />
                      <div>
                        <div className="mono" style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{ratio}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 2 }}>{cat}</div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="note"><b>Caveat:</b> {canary.caveat}</div>
              <div className="note" data-kind="cold" style={{ marginTop: 8 }}>
                <b>Not measured here, and we are not going to pretend otherwise:</b>
                <ul style={{ margin: '6px 0 0 18px' }}>
                  {canary.not_measured.map((n) => <li key={n} style={{ marginTop: 3 }}>{n}</li>)}
                </ul>
              </div>
            </>
          )}
        </div>
      </section>

      {/* ----------------------------------------------------------- cost -- */}
      <section className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-head">
          <span className="panel-title">Cost · gross, overhead, net</span>
          <button className="btn" onClick={() => run('cost', () => get('/demo/cost'), setCost)}>Refresh</button>
        </div>
        <div className="panel-body">
          {!cost || cost.requests === 0 ? (
            <p className="payload-empty">
              No requests yet this session. Send one on the Transit page and the ledger fills in.
            </p>
          ) : (
            <>
              <div className="cols cols-3" style={{ marginBottom: 14 }}>
                <div className="stat" data-tone="warm">
                  <span className="v">{usd(cost.baseline_spend_usd, 4)}</span>
                  <span className="k">baseline — {cost.baseline_model}, no routing, no cache</span>
                </div>
                <div className="stat" data-tone="ok">
                  <span className="v">{usd(cost.gross_saving_usd, 4)}</span>
                  <span className="k">gross saving</span>
                </div>
                <div className="stat" data-tone="cold">
                  <span className="v">{usd(cost.net_saving_usd, 4)}</span>
                  <span className="k">net, after our own overhead of {usd(cost.our_overhead_usd, 4)}</span>
                </div>
              </div>
              <pre className="dump">{cost.summary}</pre>
              <div className="note" style={{ marginTop: 12 }}>
                Gross and net are reported together on purpose. A governance layer that only quotes
                the gross figure is hiding the cost of running itself — and the first thing a
                sceptical buyer asks is what the checkpoint costs them.
              </div>
            </>
          )}
        </div>
      </section>

      {/* ----------------------------------------------------------- bias -- */}
      <section className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-head">
          <span className="panel-title">Bias · aggregate, because there is no other kind</span>
          <button className="btn" disabled={busy === 'bias'}
            onClick={() => run('bias', () => post('/demo/bias', {}), setBias)}>
            {busy === 'bias' ? 'Probing…' : 'Run counterfactual pairs'}
          </button>
        </div>
        <div className="panel-body">
          <div className="note" data-kind="cold" style={{ marginBottom: 12 }}>
            <b>There is no per-response bias score on this page and there never will be.</b> A model
            that favours one group 70% of the time produces no individually-detectable response —
            each one looks reasonable alone. Anyone showing you a per-response bias number is doing
            toxicity detection and mislabelling it.
          </div>

          {!bias ? (
            <p className="payload-empty">
              Runs the same request twice with one attribute changed, then counts outcomes. We vary
              the attribute rather than masking it: masking is fairness through unawareness — the
              model reconstructs it from everything else, so it removes our ability to measure bias
              without removing the bias.
            </p>
          ) : (
            <>
              <table className="grid" style={{ marginBottom: 12 }}>
                <thead><tr><th>Attribute changed</th><th>Outcome A</th><th>Outcome B</th><th>Diverged</th></tr></thead>
                <tbody>
                  {bias.pairs.map((p, i) => (
                    <tr key={i}>
                      <td className="mono">{p.variant_a} → {p.variant_b}</td>
                      <td><span className="chip">{p.outcome_a}</span></td>
                      <td><span className="chip">{p.outcome_b}</span></td>
                      <td>{p.diverged
                        ? <span className="chip" data-kind="warn">yes</span>
                        : <span className="chip">no</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="cols cols-2" style={{ marginBottom: 12 }}>
                <div className="stat" data-tone="warm">
                  <span className="v">
                    {bias.pairs.filter((p) => p.diverged).length} / {bias.pairs.length}
                  </span>
                  <span className="k">
                    pairs where changing only the name changed the outcome
                  </span>
                </div>
                <div className="stat" data-tone="cold">
                  <span className="v">{bias.report.disparity}</span>
                  <span className="k">
                    widest gap in “advance” rate between any two groups — 0 here because
                    nothing advanced, which is a fact about this run, not a clean bill of health
                  </span>
                </div>
              </div>
              <div className="note"><b>Sample size:</b> {bias.honest_caveat}</div>
            </>
          )}
        </div>
      </section>

      {/* -------------------------------------------------------- quality -- */}
      {quality && (
        <div className="cols cols-2">
          <section className="panel">
            <div className="panel-head"><span className="panel-title">Built · runs after delivery</span></div>
            <div className="panel-body">
              {quality.built.map((c) => (
                <div className="note" key={c.check} data-kind="ok" style={{ marginBottom: 8 }}>
                  <b>{c.check}</b> <span className="chip">{c.category}</span>
                  <div style={{ marginTop: 5 }}>{c.why}</div>
                  <div className="hash" style={{ marginTop: 5 }}>confidence: {c.confidence}</div>
                  <div className="hash" style={{ marginTop: 3 }}>{c.runs}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <span className="panel-title">Not built · labelled, not omitted</span>
            </div>
            <div className="panel-body">
              {quality.not_built.map((c) => (
                <div className="note" key={c.check} data-kind="cold" style={{ marginBottom: 8 }}>
                  <b>{c.check}</b> <span className="chip" data-kind="off">{c.status}</span>
                  <div style={{ marginTop: 5 }}>{c.why}</div>
                </div>
              ))}
              <div className="note" style={{ marginTop: 4 }}>
                An honest gap reads as scope control. An empty function where a feature was promised
                reads as vapour — and on a public repo, a reviewer opens the file.
              </div>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
