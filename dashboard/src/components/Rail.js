'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

/* Ported from controlplane-screens-built/project/IconRail.dc.html.
 *
 * The rail replaces the old horizontal nav links entirely - navigation now
 * lives here, one circle per page, in demo order. Nav.js keeps only the
 * health strip.
 */

const ICON = {
  transit: (c) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <path d="M2 9h13" stroke={c} strokeWidth="1.6" strokeLinecap="round" />
      <path d="M11 4l4.5 5-4.5 5" stroke={c} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  ),
  profiles: (c) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <circle cx="6.5" cy="8" r="3.4" stroke={c} strokeWidth="1.5" />
      <circle cx="11.5" cy="8" r="3.4" stroke={c} strokeWidth="1.5" />
    </svg>
  ),
  review: (c) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <circle cx="9" cy="9" r="7" stroke={c} strokeWidth="1.5" />
      <path d="M5.8 9.2l2.1 2.1 4.3-4.6" stroke={c} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  ),
  chain: (c) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="2" y="5.5" width="8" height="7" rx="3.5" stroke={c} strokeWidth="1.5" />
      <rect x="8" y="5.5" width="8" height="7" rx="3.5" stroke={c} strokeWidth="1.5" />
    </svg>
  ),
  measures: (c) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="3" y="9" width="3" height="6" rx="1" fill={c} />
      <rect x="7.5" y="5" width="3" height="10" rx="1" fill={c} />
      <rect x="12" y="7.5" width="3" height="7.5" rx="1" fill={c} />
    </svg>
  ),
};

const ITEMS = [
  ['/', 'transit', 'Transit'],
  ['/policy', 'profiles', 'Profiles'],
  ['/queue', 'review', 'Review'],
  ['/verify', 'chain', 'Chain'],
  ['/trust', 'measures', 'Measures'],
];

export default function Rail() {
  const path = usePathname();

  return (
    <nav className="rail" aria-label="Sections">
      <div className="rail-logo" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <circle cx="9" cy="9" r="7.5" stroke="#F1F3F7" strokeWidth="1.6" />
          <circle cx="9" cy="9" r="2.4" fill="#F1F3F7" />
        </svg>
      </div>

      {ITEMS.map(([href, key, label]) => {
        const active = path === href;
        return (
          <Link
            key={href}
            href={href}
            className="rail-item"
            data-active={active}
            title={label}
            aria-label={label}
            aria-current={active ? 'page' : undefined}
          >
            {ICON[key](active ? '#FFFFFF' : '#3F4552')}
          </Link>
        );
      })}

      <div className="rail-spacer" />

      <div className="rail-settings" aria-hidden="true" title="Settings">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <path d="M3 6.5h12M3 9h12M3 11.5h8" stroke="#8A91A0" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="9" cy="6.5" r="1.6" fill="#8A91A0" />
          <circle cx="13" cy="9" r="1.6" fill="#8A91A0" />
          <circle cx="6" cy="11.5" r="1.6" fill="#8A91A0" />
        </svg>
      </div>
    </nav>
  );
}
