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
  const [jurisdiction, setJurisdiction] = useState(null);
  const [jurisdictions, setJurisdictions] = useState([]);
  const [profiles, setProfiles] = useState([]);
  //: Which settings below actually change behaviour. From the server's
  //: own policy/enforcement.py, never guessed here.
  const [enf, setEnf] = useState({});
  const [result, setResult] = useState(null);
  const [floorResult, setFloorResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const load = () =>
    get('/demo/profiles')
      .then((d) => {
        setProfiles(d.profiles); setVersion(d.version); setJurisdiction(d.jurisdiction);
        setEnf(d.enforcement ?? {});
      })
      .catch((e) => setErr(e.message));

  useEffect(() => {
    load();
    get('/demo/jurisdictions').then((d) => setJurisdictions(d.options)).catch(() => {});
  }, []);

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

  const applyJurisdiction = async (code) => {
    setBusy(true); setErr(null); setResult(null);
    try {
      setFloorResult(await post('/demo/jurisdiction', { code: code || null }));
      await load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <span className="eyebrow">Three use cases, three policies, one checkpoint</span>
      <h1 className="title">Profiles</h1>
      <p className="lede">
        There is no single correct configuration of this gateway, and pretending otherwise is how
        governance products become unusable. Each use case compiles to a named profile with a
        content fingerprint. Change one here and the data plane picks it up on the next request —
        <strong> with no restart and no network call on the hot path</strong>.
      </p>

      <section className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-body" style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <span className="panel-title" style={{ fontSize: 13.5 }}>Jurisdiction</span>
          <select
            value={jurisdiction ?? ''}
            disabled={busy}
            onChange={(e) => applyJurisdiction(e.target.value)}
          >
            <option value="">none — profiles run exactly as authored</option>
            {jurisdictions.map((j) => (
              <option key={j.code} value={j.code}>{j.name}</option>
            ))}
          </select>
          {jurisdiction && (
            <span className="chip mono">
              {jurisdictions.find((j) => j.code === jurisdiction)?.name}
            </span>
          )}
          <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>
            a floor every profile is clamped against — stricter is always allowed, looser never is
          </span>
        </div>
      </section>

      {err && <div className="note" data-kind="stop" style={{ marginBottom: 16 }}>{err}</div>}

      <div className="cols cols-3">
        {profiles.map((p) => (
          <section className="panel" key={p.name}>
            <div className="panel-head">
              <span className="panel-title">{p.name}</span>
              <span className="chip mono">{p.fingerprint}</span>
            </div>
            <div className="panel-body">
              <p style={{ color: 'var(--text-dim)', fontSize: 12.5, marginBottom: 14 }}>
                {p.description}
              </p>

              <Row k="blocks at confidence" v={p.decision.block_at} state={enf["decision.block_at"]} />
              <Row k="review band" v={`${p.decision.review_band[0]} – ${p.decision.review_band[1]}`} state={enf["decision.review_band"]} />
              <Row k="flag budget / 100" v={p.decision.flag_budget_per_100} state={enf["decision.flag_budget_per_100"]} />
              <Row k="reviews everything" v={p.decision.always_review ? 'yes' : 'no'} state={enf["decision.always_review"]} />
              <Row k="streaming" v={`${p.streaming.mode}${p.streaming.buffered ? '' : ' · unbuffered'}`} />
              <Row k="hold window" v={`${p.streaming.overlap_chars} chars`} state={enf["streaming.overlap_chars"]} />
              <Row k="hallucination tier" v={p.quality.hallucination_tier} state={enf["quality.hallucination_tier"]} />
              <Row k="exemptions" v={p.decision.exempt.length ? p.decision.exempt.join(', ') : 'none'} />
              <Row k="session record cap" v={p.session.max_records_per_session} state={enf["session.max_records_per_session"]} />
              <Row k="audit level" v={p.audit_level} state={enf["audit_level"]} />

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

      {floorResult && (
        <section className="panel" style={{ marginTop: 16 }} data-role="session">
          <div className="panel-head">
            <span className="panel-title">
              {floorResult.jurisdiction
                ? `Clamped to the ${jurisdictions.find((j) => j.code === floorResult.jurisdiction)?.name} floor`
                : 'Floor cleared — profiles run as authored'}
            </span>
            <span className="chip mono">policy v{floorResult.version}</span>
          </div>
          <div className="panel-body">
            {Object.values(floorResult.profiles).every((p) => Object.keys(p.clamped).length === 0) ? (
              <p className="payload-empty">
                {floorResult.jurisdiction
                  ? 'nothing moved — every profile already meets this floor on its own'
                  : 'no floor in force'}
              </p>
            ) : (
              Object.entries(floorResult.profiles).map(([name, p]) => (
                Object.keys(p.clamped).length > 0 && (
                  <div key={name} style={{ marginBottom: 14 }}>
                    <div className="composer-row" style={{ marginBottom: 6 }}>
                      <span className="chip">{name}</span>
                      <span className="hash mono">
                        {p.fingerprint.before} → {p.fingerprint.after}
                      </span>
                    </div>
                    <table className="grid">
                      <thead><tr><th>Path</th><th>Was</th><th>Floor</th></tr></thead>
                      <tbody>
                        {Object.entries(p.clamped).map(([path, [was, now]]) => (
                          <tr key={path}>
                            <td className="mono">{path}</td>
                            <td className="mono" style={{ color: 'var(--text-faint)' }}>{was}</td>
                            <td className="mono" style={{ color: 'var(--inside)' }}>
                              {now} <span className="chip" data-kind="warn" style={{ marginLeft: 6 }}>clamped by floor</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )
              ))
            )}
            <div className="note" style={{ marginTop: 8 }}>
              A profile may be stricter than its jurisdiction demands; it may never be looser.
              Nothing here changed which profile you authored — only what the compiler will let
              it get away with.
            </div>
          </div>
        </section>
      )}

      {result && (
        <section className="panel" style={{ marginTop: 16 }}>
          <div className="panel-head">
            <span className="panel-title">Published · policy v{result.version}</span>
            <span className="chip mono">
              {result.fingerprint.before} → {result.fingerprint.after}
            </span>
          </div>
          <div className="panel-body">
            {Object.keys(result.diff).length === 0 ? (
              <p className="payload-empty">
                nothing changed — the fingerprint is identical, so this request had no effect
                {jurisdiction && ', most likely because the jurisdiction floor held it where it was'}
              </p>
            ) : (
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
            )}
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
        <div className="panel-head"><span className="panel-title">Why the compiler refuses things</span></div>
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
            {jurisdiction && (
              <button className="btn btn-danger" disabled={busy}
                onClick={() => patch('internal-knowledge', 'decision', 'block_at', 0.97)}>
                Try to loosen below the {jurisdictions.find((j) => j.code === jurisdiction)?.name} floor
              </button>
            )}
          </div>
          <div className="note" style={{ marginTop: 12 }} data-kind="cold">
            The first three are refused outright by <span className="mono">compile_profile</span>,
            with the reason — blocking a credential is not a tunable, so it is never exposed as a
            setting a tired reviewer can switch off one override at a time.
          </div>
          {jurisdiction && (
            <div className="note" style={{ marginTop: 8 }} data-kind="cold">
              The fourth compiles fine and changes nothing: under a jurisdiction, a request for
              <span className="mono"> block_at: 0.97</span> is silently held at the floor instead.
              Same fingerprint before and after is the proof — check the diff panel below after
              clicking it.
            </div>
          )}
        </div>
      </section>
    </>
  );
}

/* One setting. `state` comes from the server's enforcement map
 * (policy/enforcement.py): a field that is declared but that no code reads
 * yet is greyed and chipped, rather than sitting here looking identical to
 * the ones that work. An audit found six of those on this page; the chip is
 * how a viewer can tell them apart without reading the source. */
function Row({ k, v, state }) {
  const declaredOnly = state && state.enforced === false;
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline',
      padding: '5px 0', borderBottom: '1px solid rgba(39,49,63,0.6)', fontSize: 12.5,
      opacity: declaredOnly ? 0.55 : 1,
    }}>
      <span style={{ color: 'var(--text-faint)' }}>
        {k}
        {declaredOnly && (
          <span className="chip" data-kind="off" style={{ marginLeft: 6, fontSize: 10 }}
                title={state.note}>declared only</span>
        )}
      </span>
      <span className="mono" style={{ color: 'var(--text)' }}>{String(v)}</span>
    </div>
  );
}
