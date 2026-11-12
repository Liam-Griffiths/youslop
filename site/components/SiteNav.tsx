import { NAME, GITHUB_URL, RELEASES_URL } from '@/lib/brand';

export default function SiteNav() {
  return (
    <header className="wrap nav">
      <a className="wordmark" href="/" aria-label={`${NAME} home`}>
        <img src="/mark.svg" alt="" width={28} height={28} />
        {NAME}
      </a>
      <nav aria-label="Site">
        <ul>
          <li><a href="/#features">Features</a></li>
          <li><a href="/download/">Download</a></li>
          <li><a href={RELEASES_URL}>Releases</a></li>
          <li><a href={GITHUB_URL}>GitHub</a></li>
        </ul>
      </nav>
    </header>
  );
}
