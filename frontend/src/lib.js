// React and htm are loaded as globals by index.html; htm gives JSX-like templates without a build step.
const { createElement, useState, useEffect, useRef, useMemo } = React;
export { useState, useEffect, useRef, useMemo };
export const html = htm.bind(createElement);

const query = new URLSearchParams(location.search);
// Served by the API at /app/ -> same origin; otherwise the API on localhost:8000 (override with ?api=http://host:port)
export const API = query.get('api') || (location.pathname.startsWith('/app/') ? '' : 'http://localhost:8000');
export const START_PARCEL = query.get('parcel');

// The session token of the signed-in user. Storage can be blocked (private window): then nobody stays signed in.
const TOKEN_KEY = 'agronomicon:token';
export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
}
export function setToken(token) {
  try { if (token) localStorage.setItem(TOKEN_KEY, token); else localStorage.removeItem(TOKEN_KEY); } catch (e) { /* blocked */ }
}

/** Throws an Error with message 'HTTP <status>', plus status, detail (the server's message) and fields (field -> message). */
export async function api(path, options = {}) {
  const token = getToken();
  const headers = { ...(options.body && { 'Content-Type': 'application/json' }), ...(token && { Authorization: 'Bearer ' + token }) };
  const response = await fetch(API + path, { ...options, headers });
  if (!response.ok) {
    const error = Object.assign(new Error('HTTP ' + response.status), { status: response.status, detail: '', fields: {} });
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') error.detail = body.detail;
      error.fields = body.fields || {};
    } catch (e) { /* not JSON */ }
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

export function send(method, path, data) {
  return api(path, { method, body: data === undefined ? undefined : JSON.stringify(data) });
}

/** The page from the address: '#/profile' -> { page: 'profile', params }. '' is the fields page. */
function readRoute() {
  const [page, query] = location.hash.replace(/^#\/?/, '').split('?');
  return { page, params: new URLSearchParams(query || '') };
}
/** { page, params, navigate }. navigate() updates the route at once, in the same render as any state set beside it;
 * waiting for 'hashchange' would show one render of the old page with the new state. */
export function useRoute() {
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    const changed = () => { setRoute(readRoute()); window.scrollTo(0, 0); };
    addEventListener('hashchange', changed);
    return () => removeEventListener('hashchange', changed);
  }, []);
  function navigate(page) {
    location.hash = '#/' + page;
    setRoute(readRoute());
  }
  return { ...route, navigate };
}

export function num(value, digits = 1) {
  return value == null ? '—' : Number(value).toLocaleString('ro-RO', { maximumFractionDigits: digits });
}

export function hm(date) {
  return date.toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' });
}

export function day(iso, withYear = true) {
  return new Date(iso).toLocaleDateString('ro-RO', { day: 'numeric', month: 'short', ...(withYear && { year: 'numeric' }) });
}

/** "azi, 14:05" for today, "3 oct., 14:05" otherwise. */
export function when(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return (d.toDateString() === new Date().toDateString() ? 'azi' : day(iso, false)) + ', ' + hm(d);
}
