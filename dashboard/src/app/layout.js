import './globals.css';
import { Plus_Jakarta_Sans, Outfit, JetBrains_Mono } from 'next/font/google';
import Nav from '@/components/Nav';
import Rail from '@/components/Rail';

/* One geometric family for everything except the page title, which is the
 * one place Outfit earns its keep - five 52px headings, nowhere else. */
const display = Plus_Jakarta_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700', '800'],
  variable: '--font-display',
});

const pageTitle = Outfit({
  subsets: ['latin'],
  weight: ['600', '700', '800'],
  variable: '--font-page-title',
});

const mono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-mono',
});

export const metadata = {
  title: 'ControlPlane',
  description:
    'The layer that lets a regulated organisation put real company data into a third-party model, without the sensitive parts ever leaving the building.',
};

export default function RootLayout({ children }) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${pageTitle.variable} ${mono.variable}`}
    >
      <body>
        <div className="page">
          <Nav />
          <div className="frame">
            <Rail />
            <div className="shell">{children}</div>
          </div>
        </div>
      </body>
    </html>
  );
}
