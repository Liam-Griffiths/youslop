import manifest from './media-manifest.json';

export type MediaEntry = { hash: string; width: number; height: number; widths: number[]; blur: string };
export type MediaName = keyof typeof manifest;
export const MEDIA = manifest as unknown as Record<string, MediaEntry>;
export type TrailerEntry = { src: string; mobile: string; poster: string; hash: string; seconds: number };
// Written by site/tools/trailer.py; absent until the trailer has been cut.
export const TRAILER = (manifest as Record<string, unknown>)['_trailer'] as TrailerEntry | undefined;
// One switch moves media to a CDN later: set NEXT_PUBLIC_MEDIA_BASE at build time.
export const MEDIA_BASE = (process.env.NEXT_PUBLIC_MEDIA_BASE || '/media').replace(/\/$/, '');

/** The smallest pre-built width that is at least `want`, or the largest there is. */
export function pickWidth(entry: MediaEntry, want: number): number {
  return entry.widths.find((w) => w >= want) ?? entry.widths[entry.widths.length - 1];
}

export function mediaUrl(name: string, want: number, ext: 'avif' | 'webp'): string {
  const entry = MEDIA[name];
  if (!entry) throw new Error(`Unknown site image "${name}". Run site/tools/build_images.py.`);
  return `${MEDIA_BASE}/${name}-${entry.hash}-${pickWidth(entry, want)}.${ext}`;
}
