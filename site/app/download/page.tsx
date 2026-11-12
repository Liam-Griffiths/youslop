import type { Metadata } from 'next';
import { NAME, RELEASES_URL, BUILD_DOC_URL } from '@/lib/brand';
import { PLATFORMS, platformHref } from '@/lib/releases';

export const metadata: Metadata = { title: `Download · ${NAME}` };

// T19.3 replaces this with every release from GitHub Releases.
export default function Download() {
  return (
    <section className="wrap page" aria-labelledby="dl-title">
      <h1 id="dl-title">Download</h1>
      <p>Builds for each platform are published on GitHub Releases, with notes for every version.</p>
      <ul className="builds">
        {PLATFORMS.map((p) => (
          <li key={p.id}>
            <a href={platformHref(p)}>
              <strong>{p.label}</strong>
              <span>{p.detail}</span>
            </a>
          </li>
        ))}
      </ul>
      <p><a href={RELEASES_URL}>All releases</a> · <a href={BUILD_DOC_URL}>Build from source</a></p>
    </section>
  );
}
