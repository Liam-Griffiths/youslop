import { NAME, GITHUB_URL, RELEASES_URL, LICENSE_NAME, LICENSE_URL } from '@/lib/brand';

export default function SiteFooter() {
  return (
    <footer className="wrap footer">
      <nav aria-label="Footer">
        <a href={LICENSE_URL}>Licence: {LICENSE_NAME}</a>
        <a href={GITHUB_URL}>GitHub</a>
        <a href={RELEASES_URL}>Releases</a>
      </nav>
      <p>
        {NAME} is free software. Set in Archivo, Inter and JetBrains Mono, all under the{' '}
        <a href="/fonts/OFL.txt">SIL Open Font License</a>. Screenshots show the bundled example
        project, made from public-domain pictures.
      </p>
    </footer>
  );
}
