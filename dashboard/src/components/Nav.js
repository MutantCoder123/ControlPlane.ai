'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { get } from '@/lib/api';

const LINKS = [
  ['/', 'Transit'],
  ['/policy', 'Profiles'],
  ['/queue', 'Review'],
  ['/verify', 'Chain'],
  ['/trust', 'Measures'],
];

export default function Nav() {
  const path = usePathname();
  const [health, setHealth] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    get('/demo/health').then(setHealth).catch((e) => setErr(e.message));
  }, []);

  const ok = health?.ok ?? null;

  return (
    <header className="topbar">
      <span className="brand">ControlPlane</span>

      <nav className="nav">
        {LINKS.map(([href, label]) => (
          <Link key={href} href={href} data-active={path === href}>
            {label}
          </Link>
        ))}
      </nav>

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
