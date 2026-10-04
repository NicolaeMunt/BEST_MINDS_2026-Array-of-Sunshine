// A block that folds open and shut with a smooth height change. Remembers its state per storageKey.
import { html, useState } from './lib.js';

function remembered(key, fallback) {
  try {
    const value = key && localStorage.getItem('fold:' + key);
    return value == null ? fallback : value === '1';
  } catch (e) {
    return fallback;
  }
}

export function Fold({ title, extra, storageKey, open: initial = true, className = '', children }) {
  const [open, setOpen] = useState(() => remembered(storageKey, initial));
  function toggle() {
    setOpen(o => {
      try { if (storageKey) localStorage.setItem('fold:' + storageKey, o ? '0' : '1'); } catch (e) { /* private window */ }
      return !o;
    });
  }
  // inert keeps the folded content out of the tab order and away from screen readers.
  return html`<div className=${'fold ' + className + (open ? ' is-open' : '')}>
    <h2 className="fold-head">
      <button aria-expanded=${open} onClick=${toggle}>
        <span className="fold-title">${title}</span>
        ${extra != null && html`<span className="fold-extra">${extra}</span>`}
        <svg className="fold-chevron" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
          <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </h2>
    <div className="fold-body" inert=${open ? undefined : ''}>
      <div className="fold-inner">${children}</div>
    </div>
  </div>`;
}
