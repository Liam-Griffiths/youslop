'use client';
import { useEffect, useState } from 'react';
import { PLATFORMS, platformHref, type Platform } from '@/lib/releases';

function detect(): Platform['id'] | null {
  const ua = navigator.userAgent;
  if (/Mac OS X|Macintosh/.test(ua) && !/iPhone|iPad/.test(ua)) return 'mac';
  if (/Windows/.test(ua)) return 'windows';
  if (/Linux/.test(ua) && !/Android/.test(ua)) return 'linux';
  return null;
}

/** One primary button for the visitor's system. Renders a neutral label until it knows. */
export default function DownloadButton() {
  const [platform, setPlatform] = useState<Platform | null>(null);
  useEffect(() => {
    const id = detect();
    setPlatform(PLATFORMS.find((p) => p.id === id) ?? null);
  }, []);
  const href = platform ? platformHref(platform) : '/download/';
  return (
    <a className="btn btn-primary" href={href}>
      {platform ? `Download for ${platform.label}` : 'Download'}
    </a>
  );
}
