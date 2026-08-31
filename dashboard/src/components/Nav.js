'use client';

import { useEffect, useState } from 'react';
import { get } from '@/lib/api';

/* Just the health strip now - the Rail owns navigation between pages, so
 * this keeps only the thing that isn't a link: whether the backend and the
 * local model are actually reachable, checked live rather than assumed. */
export default function Nav() {
  const [health, setHealth] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    get('/demo/health').then(setHealth).catch((e) => setErr(e.message));
  }, []);

  const ok = health?.ok ?? null;

  return (
    <header className="topbar">
      <span className="brand">ControlPlane</span>

      <div className="status">
        {err ? (
          <span>
            <span className="dot" data-ok="false" />
            demo server unreachable — run <b>python -m controlplane.demo.server</b>
          </span>
        ) : (
          <>
            <span>
              <span className="dot" data-ok={ok === null ? undefined : ok} />
              {health ? health.model.name : 'checking model'}
            </span>
            {health && (
              <>
                <span>
                  policy <b>v{health.policy_version}</b>
                </span>
                <span>
                  priced as <b>{health.priced_as}</b>
                </span>
              </>
            )}
          </>
        )}
      </div>
    </header>
  );
}
