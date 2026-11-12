'use client';
import { useEffect, useState } from 'react';

type Mode = 'system' | 'light' | 'dark';
const KEY = 'theme';

function apply(mode: Mode) {
  const root = document.documentElement;
  if (mode === 'system') delete root.dataset.theme;
  else root.dataset.theme = mode;
}

const ICONS: Record<Mode, React.ReactNode> = {
  system: <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="9" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4"/><path d="M5.5 14h5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>,
  light: <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.4"/><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6 13 13M3 13l1.4-1.4M11.6 4.4 13 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>,
  dark: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13.5 9.6A6 6 0 0 1 6.4 2.5a6 6 0 1 0 7.1 7.1Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>,
};
const LABELS: Record<Mode, string> = { system: 'Match system theme', light: 'Light theme', dark: 'Dark theme' };

/** System, light or dark. The choice is remembered in this browser only. */
export default function ThemeSwitch() {
  const [mode, setMode] = useState<Mode>('system');
  useEffect(() => {
    try {
      const saved = localStorage.getItem(KEY);
      if (saved === 'light' || saved === 'dark') setMode(saved);
    } catch { /* storage blocked: stay on system */ }
  }, []);
  const choose = (next: Mode) => {
    setMode(next);
    apply(next);
    try {
      if (next === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch { /* not remembered, still applied */ }
  };
  return (
    <div className="theme-switch" role="group" aria-label="Theme">
      {(['system', 'light', 'dark'] as Mode[]).map((m) => (
        <button key={m} type="button" aria-pressed={mode === m} aria-label={LABELS[m]} title={LABELS[m]} onClick={() => choose(m)}>
          {ICONS[m]}
        </button>
      ))}
    </div>
  );
}
