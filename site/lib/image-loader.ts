// next/image custom loader: maps (src, width) onto the pre-built width set.
// `src` is an image name from lib/media-manifest.json, never a path or URL.
import { mediaUrl } from './media';

export default function imageLoader({ src, width }: { src: string; width: number; quality?: number }): string {
  return mediaUrl(src, width, 'webp');
}
