import data from './releases.json';
import { RELEASES_URL } from './brand';

export type Platform = { id: 'mac' | 'linux' | 'windows'; label: string; detail: string; asset: string | null };
export const PLATFORMS = data.platforms as Platform[];
export const LATEST = data.latest as string | null;

/** The build's download link once T19.3 records assets, otherwise the releases page. */
export function platformHref(p: Platform): string {
  return p.asset || (LATEST ? `${RELEASES_URL}/tag/${LATEST}` : RELEASES_URL);
}
