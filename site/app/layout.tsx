import type { Metadata, Viewport } from 'next';
import './globals.css';
import { NAME, SITE_URL } from '@/lib/brand';
import SiteNav from '@/components/SiteNav';
import SiteFooter from '@/components/SiteFooter';

const description = 'Turn an idea or a script into a researched, narrated, illustrated video on your own computer.';

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: NAME,
  description,
  openGraph: { title: NAME, description, type: 'website', url: SITE_URL },
};

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#F4F2EE' },
    { media: '(prefers-color-scheme: dark)', color: '#121214' },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preload" href="/fonts/archivo-condensed-800.woff2" as="font" type="font/woff2" crossOrigin="" />
        <link rel="preload" href="/fonts/inter-500.woff2" as="font" type="font/woff2" crossOrigin="" />
      </head>
      <body>
        <SiteNav />
        <main>{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
