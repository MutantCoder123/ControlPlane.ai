'use client';

import { useEffect, useState } from 'react';
import { get, post } from '@/lib/api';

/* Demo step 6.
 *
 * "Tamper-evident" is a claim, and a claim a judge can check is worth more
 * than one they cannot. So this page ships the falsification: edit a
 * committed entry in place, leave its hash alone, and watch verification name
 * the exact entry where the chain stops agreeing with itself.
 *
 * It is deliberately NOT called tamper-proof. An attacker with process access
 * can still append. What they cannot do is rewrite history quietly (D14).
 */
export default function Chain() {
  const [chain, setChain] = useState(null);
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const load = () => get('/demo/audit').then(setChain).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const act = async (fn) => {
    setBusy(true); setErr(null);
    try { setCheck(await fn()); await load(); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  const entries = chain?.entries ?? [];
  const broken = check && !check.ok ? check.broken_at : null;

  return (
    <>
      <h1 className="title">The log that cannot be quietly rewritten</h1>
      <p className="lede">
        Every entry hashes its own contents together with the hash before it. Edit anything,
        anywhere, and every hash after it disagrees. Note what is <strong>absent</strong> from the
        payloads: no prompt, no response, no matched value — a category, a confidence and a record
        reference are enough to reconstruct the decision and useless to anyone who steals the log.
      </p>

      {err && <div className="note" data-kind="stop" style={{ marginBottom: 16 }}>{err}</div>}

      <div className="composer-row" style={{ marginBottom: 16 }}>
        <button className="btn btn-primary" disabled={busy}
          onClick={() => act(() => post('/demo/audit/verify'))}>
          Verify the chain
        </button>
        <button className="btn btn-danger" disabled={busy || entries.length === 0}
          onClick={() => act(() => post('/demo/audit/tamper', { seq: 0, event: 'nothing_to_see_here' }))}>
          Tamper with entry #0
        </button>
        <span className="chip mono">{entries.length} entries</span>
        {chain && <span className="chip mono">head {chain.head.slice(0, 16)}…</span>}
      </div>

      {check && (
        <div className="note" data-kind={check.ok ? 'ok' : 'stop'} style={{ marginBottom: 16 }}>
          <b>{check.ok ? '✓ chain intact' : `✕ chain broken at entry #${check.broken_at}`}</b>
          <div style={{ marginTop: 6 }}>
            {check.ok
              ? `All ${check.entries} entries verify against the entry before them.`
              : `${check.reason}. Everything from #${check.broken_at} onward is now unprovable — which is exactly what an auditor needs to see, rather than a log that silently accepts the edit.`}
          </div>
          {check.claim && <div style={{ marginTop: 8, color: 'var(--text-faint)' }}>{check.claim}</div>}
        </div>
      )}

      {entries.length === 0 ? (
        <section className="panel">
          <div className="panel-body">
            <p className="payload-empty">
              The log is empty. Send a request on the Transit page and entries appear here.
            </p>
          </div>
        </section>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {entries.map((e) => (
            <section className="panel" key={e.seq}
              style={broken !== null && e.seq >= broken
                ? { borderColor: 'rgba(210,84,74,0.5)' } : undefined}>
              <div className="panel-head">
                <span className="eyebrow">
                  #{e.seq} · {e.event}
                  {broken !== null && e.seq === broken && ' · contents altered'}
                  {broken !== null && e.seq > broken && ' · unprovable from here'}
                </span>
                <span className="chip mono">{e.timestamp}</span>
              </div>
              <div className="panel-body">
                <div className="hash" style={{ marginBottom: 4 }}>
                  prev {e.prev_hash}
                </div>
                <div className="hash" style={{ marginBottom: 10, color: 'var(--outside)' }}>
                  this {e.entry_hash}
                </div>
                <pre className="dump">{JSON.stringify(e.payload, null, 2)}</pre>
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
