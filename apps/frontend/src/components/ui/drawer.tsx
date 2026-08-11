"use client";

import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; closeRef.current?.focus(); const key = (event: KeyboardEvent) => event.key === "Escape" && onClose(); window.addEventListener("keydown", key); return () => { window.removeEventListener("keydown", key); previous?.focus(); }; }, [onClose]);
  return <div className="drawer-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title"><header><h2 id="drawer-title">{title}</h2><button ref={closeRef} className="icon-button" onClick={onClose} aria-label="Close detail"><X /></button></header><div className="drawer-content">{children}</div></section></div>;
}
