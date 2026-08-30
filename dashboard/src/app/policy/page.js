'use client';

import { useEffect, useState } from 'react';
import { get, post } from '@/lib/api';

/* Demo step 4 and 7.
 *
 * The claim this page has to make good on: the use case is the policy unit,
 * and the tier is a function of severity x confidence x PROFILE. Without a
 * page where the same finding visibly resolves differently, route profiles
 * are decoration.
 */
export default function Profiles() {
  const [version, setVersion] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const load = () =>
    get('/demo/profiles')
      .then((d) => { setProfiles(d.profiles); setVersion(d.version); })
      .catch((e) => setErr(e.message));

  useEffect(() => { load(); }, []);

  const patch = async (profile, section, key, value) => {
    setBusy(true); setErr(null);
    try {
      setResult(await post('/demo/policy/patch', { profile, section, key, value }));
      await load();
    } catch (e) {
      setErr(e.message);
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h1 className="title">Three use cases, three policies, one checkpoint</h1>
      <p className="lede">
        There is no single correct configuration of this gateway, and pretending otherwise is how
        governance products become unusable. Each use case compiles to a named profile with a
        content fingerprint. Change one here and the data plane picks it up on the next request —
        <strong> with no restart and no network call on the hot path</strong>.
      </p>

      {err && <div className="note" data-kind="stop" style={{ marginBottom: 16 }}>{err}</div>}

      <div className="cols cols-3">
        {profiles.map((p) => (
          <section className="panel" key={p.name}>
            <div className="panel-head">
              <span className="eyebrow">{p.name}</span>
              <span className="chip mono">{p.fingerprint}</span>
            </div>
            <div className="panel-body">
              <p style={{ color: 'var(--text-dim)', fontSize: 12.5, marginBottom: 14 }}>
                {p.description}
              </p>

              <Row k="blocks at confidence" v={p.decision.block_at} />
              <Row k="review band" v={`${p.decision.review_band[0]} – ${p.decision.review_band[1]}`} />
              <Row k="flag budget / 100" v={p.decision.flag_budget_per_100} />
              <Row k="reviews everything" v={p.decision.always_review ? 'yes' : 'no'} />
              <Row k="streaming" v={`${p.streaming.mode}${p.streaming.buffered ? '' : ' · unbuffered'}`} />
              <Row k="hold window" v={`${p.streaming.overlap_chars} chars`} />
              <Row k="hallucination tier" v={p.quality.hallucination_tier} />
              <Row k="exemptions" v={p.decision.exempt.length ? p.decision.exempt.join(', ') : 'none'} />

              <div className="composer-row" style={{ marginTop: 14 }}>
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => patch(p.name, 'decision', 'block_at',
                    Number((p.decision.block_at <= 0.6 ? 0.9 : p.decision.block_at - 0.15).toFixed(2)))}
                >
                  {p.decision.block_at <= 0.6 ? 'Reset threshold' : 'Tighten by 0.15'}
                </button>
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => patch(p.name, 'streaming', 'mode',
                    p.streaming.mode === 'interactive' ? 'throughput' : 'interactive')}
                >
                  Switch to {p.streaming.mode === 'interactive' ? 'throughput' : 'interactive'}
                </button>
              </div>
            </div>
          </section>
        ))}
      </div>

      {result && (
        <section className="panel" style={{ marginTop: 16 }}>
          <div className="panel-head">
            <span className="eyebrow">Published · policy v{result.version}</span>
            <span className="chip mono">
              {result.fingerprint.before} → {result.fingerprint.after}
            </span>
          </div>
          <div className="panel-body">
            <table className="grid">
              <thead>
                <tr><th>Path</th><th>Was</th><th>Now</th></tr>
              </thead>
              <tbody>
                {Object.entries(result.diff).map(([path, [was, now]]) => (
                  <tr key={path}>
                    <td className="mono">{path}</td>
                    <td className="mono" style={{ color: 'var(--text-faint)' }}>{was}</td>
                    <td className="mono" style={{ color: 'var(--inside)' }}>{now}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="note" style={{ marginTop: 12 }}>
              Two checkpoints holding the same fingerprint are provably running the same policy,
              which is the question an auditor actually asks. And the reason the next request
              behaves differently is this diff — not <b>“the model learned”</b>, which is not an
              answer a regulator accepts.
            </div>
          </div>
        </section>
      )}

      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head"><span className="eyebrow">Why the compiler refuses things</span></div>
        <div className="panel-body">
          <p style={{ color: 'var(--text-dim)', marginBottom: 12 }}>
            Validation happens once, when a policy is authored — never on the hot path. A typo is a
            silent security downgrade if you ignore it, so <span className="mono">block_credential: true</span>{' '}
            fails to compile rather than quietly not applying. Try it:
          </p>
          <div className="composer-row">
            <button className="btn btn-danger" disabled={busy}
              onClick={() => patch('internal-knowledge', 'inbound', 'block_credentials', false)}>
              Try to disable credential blocking
            </button>
            <button className="btn btn-danger" disabled={busy}
              onClick={() => patch('internal-knowledge', 'decision', 'exempt', ['pattern:api_key'])}>
              Try to exempt API keys
            </button>
            <button className="btn btn-danger" disabled={busy}
              onClick={() => patch('internal-knowledge', 'inbound', 'block_credential', true)}>
              Try a misspelled key
            </button>
          </div>
          <div className="note" style={{ marginTop: 12 }} data-kind="cold">
            All three are refused by <span className="mono">compile_profile</span>, with the reason.
            Blocking a credential is not a tunable — there is no legitimate reason to send one to a
            model, so it is not exposed as a setting a tired reviewer can switch off one override
            at a time.
          </div>
        </div>
      </section>
    </>
  );
}

function Row({ k, v }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', gap: 12,
      padding: '5px 0', borderBottom: '1px solid rgba(39,49,63,0.6)', fontSize: 12.5,
    }}>
      <span style={{ color: 'var(--text-faint)' }}>{k}</span>
      <span className="mono" style={{ color: 'var(--text)' }}>{String(v)}</span>
    </div>
  );
}
