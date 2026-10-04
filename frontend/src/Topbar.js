// The bar over the profile and the administration pages.
import { html } from './lib.js';

export function Topbar({ user, page, onSignOut }) {
  const link = (to, label) => html`<a className=${'btn btn-small' + (page === to ? ' is-current' : '')} href=${'#/' + to}
    aria-current=${page === to ? 'page' : undefined}>${label}</a>`;
  return html`<header className="topbar">
    <a className="topbar-brand" href="#/">
      <img src="assets/logo-mark.png" alt="" width="44" height="44" />
      <span className="wordmark">Agronomicon</span>
    </a>
    <nav className="topbar-nav">
      ${link('', 'Terenurile')}
      ${link('profile', 'Profilul')}
      ${user.role === 'admin' && link('admin', 'Administrare')}
      <button className="btn btn-small btn-quiet" onClick=${onSignOut}>Ieși</button>
    </nav>
  </header>`;
}
