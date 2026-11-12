import { NAME, GITHUB_URL, RELEASES_URL, LICENSE_NAME, LICENSE_URL } from '@/lib/brand';
import { TRAILER } from '@/lib/media';

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
      {TRAILER && <p>
        The trailer uses the 3D models{' '}
        <a href="https://sketchfab.com/3d-models/airbus-a380-21a5de23596945c8b2f6ddc7c6dc41e0">Airbus A380</a> by JUSTGAME and{' '}
        <a href="https://sketchfab.com/3d-models/westminster-abbey-london-uk-33175190a3ab441e908bd18796c3803d">Westminster Abbey, London, UK</a>{' '}
        by Brian Trepanier, both under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>, and public-domain
        film by the Lumière brothers (1895), Paul Strand and Charles Sheeler (1921), the Prelinger Archives (1939) and NASA (1969).
      </p>}
    </footer>
  );
}
