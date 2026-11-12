'use client';
import { useEffect, useRef } from 'react';
import { MEDIA_BASE, TRAILER } from '@/lib/media';

/**
 * The silent trailer: nothing downloads until it is near the viewport, then it
 * plays muted and loops. Phones get the 720p file. Reduced motion keeps the poster.
 */
export default function Trailer({ label }: { label: string }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const video = ref.current;
    if (!video || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const seen = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) video.play().catch(() => {});
      else video.pause();
    }, { threshold: 0.25 });
    seen.observe(video);
    return () => seen.disconnect();
  }, []);
  if (!TRAILER) return null;
  return (
    <video ref={ref} className="trailer-video" muted playsInline loop preload="none"
      poster={`${MEDIA_BASE}/${TRAILER.poster}`} aria-label={label} width={1920} height={1080}>
      <source src={`${MEDIA_BASE}/${TRAILER.mobile}`} type="video/webm" media="(max-width: 820px)" />
      <source src={`${MEDIA_BASE}/${TRAILER.src}`} type="video/webm" />
    </video>
  );
}
