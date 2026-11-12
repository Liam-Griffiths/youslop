import { getImageProps } from 'next/image';
import { MEDIA, mediaUrl } from '@/lib/media';

type Props = {
  name: string;
  alt: string;
  sizes?: string;
  priority?: boolean;
  className?: string;
  /** A tighter crop (from media-src/crops.json) served at phone widths. */
  mobile?: string;
};
const PHONE = '(max-width: 640px)';

/**
 * A screenshot from the pre-built set: AVIF first, WebP as the fallback, a
 * blurred placeholder while it loads, and lazy loading unless it's `priority`.
 * Both sources go through the same width rules as the next/image loader.
 */
export default function Shot({ name, alt, sizes = '(min-width: 1100px) 640px, 92vw', priority = false, className, mobile }: Props) {
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
  const crop = mobile && MEDIA[mobile] ? MEDIA[mobile] : null;
  const phone = crop && mobile ? {
    avif: getImageProps({ ...common, src: mobile, width: crop.width, height: crop.height, sizes: '92vw',
      loader: ({ src, width }) => mediaUrl(src, width, 'avif') }).props,
    webp: getImageProps({ ...common, src: mobile, width: crop.width, height: crop.height, sizes: '92vw' }).props,
  } : null;
  return (
    <picture className={className}>
      {phone && <source media={PHONE} type="image/avif" srcSet={phone.avif.srcSet} sizes={phone.avif.sizes} />}
      {phone && <source media={PHONE} type="image/webp" srcSet={phone.webp.srcSet} sizes={phone.webp.sizes} />}
      <source type="image/avif" srcSet={avif.srcSet} sizes={avif.sizes} />
      <img {...img} alt={alt} />
    </picture>
  );
}
