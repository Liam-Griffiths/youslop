'use client';
import { useRef } from 'react';

type Props = {
  label: string;
  title: string;
  text: string;
  more: string;
  thumb: React.ReactNode;
  large: React.ReactNode;
};

/**
 * A screenshot that opens large in a dialog with its explanation. The large
 * image sits in the closed dialog, so it only downloads once it's opened.
 */
export default function Zoom({ label, title, text, more, thumb, large }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const open = () => dialog.current?.showModal();
  const close = () => dialog.current?.close();
  return (
    <>
      <button type="button" className="zoom" onClick={open} aria-haspopup="dialog" aria-label={`View larger: ${title}`}>
        {thumb}
        <span className="zoom-hint">View larger</span>
      </button>
      <dialog ref={dialog} className="expanded" aria-label={title}
        onClick={(e) => { if (e.target === e.currentTarget) close(); }}>
        <div className="sheet">
          <div className="frame">{large}</div>
          <div className="text">
            <span className="label">{label}</span>
            <h3>{title}</h3>
            <p>{text}</p>
            <p>{more}</p>
          </div>
        </div>
        <button type="button" className="close" onClick={close} aria-label="Close">×</button>
      </dialog>
    </>
  );
}
