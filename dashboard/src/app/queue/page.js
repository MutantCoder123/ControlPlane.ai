'use client';

import { useEffect, useState } from 'react';
import { get, post, pct } from '@/lib/api';

/* Demo step 5 and 7 — the loop closing.
 *
 * A human does not get called on every flag. They get called on the MIDDLE of
 * the confidence range, because the extremes are exactly where automation is
 * reliable and the middle is where it is not.
 *
 * Then the verdicts aggregate, and once there is enough of them the tuner
 * proposes a policy change with the evidence attached. That is the answer to
 * "how does it improve without retraining?" (D24): thresholds and exception
 * lists, never model weights, so a customer can read the diff.
 */
export default function Review() {
  const [queue, setQueue] = useState(null);
  const [last, setLast] = useState(null);
  const [applied, setApplied] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const load = () => get('/demo/queue').then(setQueue).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const resolve = async (item_id, verdict) => {
    setBusy(true); setErr(null);
    try { setLast(await post('/demo/queue/resolve', { item_id, verdict })); await load(); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  const apply = async () => {
    setBusy(true); setErr(null);
    try { setApplied(await post('/demo/queue/apply')); await load(); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  const pending = queue?.pending ?? [];

  return (
    <>
      <span className="eyebrow">Where a human is worth interrupting</span>
      <h1 className="title">Review</h1>
      <p className="lede">
        Not on every flag — on the middle of the confidence range, and only where the harm cannot
        be undone. A reversible finding with evidence gets shown to the reader instead, which is
        cheaper and adds no safety a human would have added. <strong>Over-flagging is tuned, not
        solved</strong>, and sending every uncertain hallucination to a person is how the queue
        becomes noise.
      </p>

      {err && <div className="note" data-kind="stop" style={{ marginBottom: 16 }}>{err}</div>}

      <div className="cols cols-3" style={{ marginBottom: 16 }}>
        <section className="panel"><div className="panel-body">
          <div className="stat" data-tone="cold">
            <span className="v">{pending.length}</span>
            <span className="k">awaiting a verdict</span>
          </div>
        </div></section>
        <section className="panel"><div className="panel-body">
          <div className="stat" data-tone="warm">
            <span className="v">{queue ? pct(queue.override_rate) : '--'}</span>
            <span className="k">override rate — the number we look worst on, shown first</span>
          </div>
        </div></section>
        <section className="panel"><div className="panel-body">
          <div className="stat">
            <span className="v">{queue?.resolved ?? '--'}</span>
            <span className="k">resolved this session</span>
          </div>
        </div></section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <span className="panel-title">Pending</span>
          <span className="chip mono">no prompt, no response, no user — references only</span>
        </div>
        {pending.length === 0 ? (
          <div className="panel-body">
            <p className="payload-empty">
              Empty. Items land here when a decision reaches the review tier — try the
              decision-support profile on the Transit page, which reviews every response because
              the legal exposure justifies the cost.
            </p>
          </div>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>Item</th><th>Profile</th><th>Category</th><th>Confidence</th>
                <th>Why you</th><th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {pending.map((i) => (
                <tr key={i.item_id}>
                  <td className="mono">{i.item_id}</td>
                  <td><span className="chip">{i.profile}</span></td>
                  <td className="mono">{i.category}<div style={{ color: 'var(--text-faint)', fontSize: 11 }}>{i.kind}</div></td>
                  <td className="mono">{i.confidence.toFixed(2)}</td>
                  <td>
                    {i.reason}
                    {i.evidence && <div style={{ color: 'var(--text-faint)', fontSize: 11.5, marginTop: 3 }}>{i.evidence}</div>}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button className="btn" disabled={busy} onClick={() => resolve(i.item_id, 'confirmed')}>Right to flag</button>
                      <button className="btn" disabled={busy} onClick={() => resolve(i.item_id, 'overridden')}>False positive</button>
                      <button className="btn" disabled={busy} onClick={() => resolve(i.item_id, 'unclear')}>Unclear</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {last && (
        <section className="panel" style={{ marginTop: 16 }}>
          <div className="panel-head">
            <span className="panel-title">What the evidence now supports</span>
            <span className="chip mono">needs {last.min_evidence} independent reviews</span>
          </div>
          <div className="panel-body">
            {last.proposals.length === 0 ? (
              <div className="note">
                Nothing proposed yet. The tuner is deliberately conservative — one annoyed reviewer
                at 5pm on a Friday should not be able to widen a hole in the detector, so it takes{' '}
                <b>{last.min_evidence}</b> independent reviews and a {'>'}66% override rate before it
                will suggest anything.
              </div>
            ) : (
              <>
                <table className="grid">
                  <thead><tr><th>Profile</th><th>Path</th><th>Proposed</th><th>Because</th></tr></thead>
                  <tbody>
                    {last.proposals.map((p, i) => (
                      <tr key={i}>
                        <td><span className="chip">{p.profile}</span></td>
                        <td className="mono">{p.path}</td>
                        <td className="mono" style={{ color: 'var(--inside)' }}>{JSON.stringify(p.proposed)}</td>
                        <td>{p.rationale}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="composer-row" style={{ marginTop: 12 }}>
                  <button className="btn btn-violet" onClick={apply} disabled={busy}>
                    Recompile and publish
                  </button>
                  <span className="chip mono">writes its own diff to the audit chain</span>
                </div>
              </>
            )}
          </div>
        </section>
      )}

      {applied && (
        <section className="panel" style={{ marginTop: 16 }}>
          <div className="panel-head">
            <span className="panel-title">Published · policy v{applied.version}</span>
          </div>
          <div className="panel-body">
            <pre className="dump">{JSON.stringify(applied.applied, null, 2)}</pre>
            <div className="note" style={{ marginTop: 12 }} data-kind="ok">
              Nothing here touched model weights. What changed is an exception list, it is written
              down, and the Chain page now carries the diff. That is the difference between a
              system that learns and one that drifts.
            </div>
          </div>
        </section>
      )}
    </>
  );
}
