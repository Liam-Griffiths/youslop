import { getImageProps } from 'next/image';
import { MEDIA, mediaUrl } from '@/lib/media';

type Props = {
  name: string;
  alt: string;
  sizes?: string;
  priority?: boolean;
  className?: string;
};

/**
 * A screenshot from the pre-built set: AVIF first, WebP as the fallback, a
 * blurred placeholder while it loads, and lazy loading unless it's `priority`.
 * Both sources go through the same width rules as the next/image loader.
 */
export default function Shot({ name, alt, sizes = '(min-width: 1100px) 640px, 92vw', priority = false, className }: Props) {
  const entry = MEDIA[name];
  const common = {
    src: name,
    alt,
    width: entry.width,
    height: entry.height,
    sizes,
    priority,
    placeholder: entry.blur as `data:image/${string}`,
  };
  const avif = getImageProps({ ...common, loader: ({ src, width }) => mediaUrl(src, width, 'avif') }).props;
  const { props: img } = getImageProps(common);
  return (
    <picture className={className}>
      <source type="image/avif" srcSet={avif.srcSet} sizes={avif.sizes} />
      <img {...img} alt={alt} />
    </picture>
  );
}
