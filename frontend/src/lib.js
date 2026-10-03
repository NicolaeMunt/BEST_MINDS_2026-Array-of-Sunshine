// React and htm are loaded as globals by index.html; htm gives JSX-like templates without a build step.
const { createElement, useState, useEffect, useRef, useMemo } = React;
export { useState, useEffect, useRef, useMemo };
export const html = htm.bind(createElement);

const query = new URLSearchParams(location.search);
// Served by the API at /app/ -> same origin; otherwise the API on localhost:8000 (override with ?api=http://host:port)
export const API = query.get('api') || (location.pathname.startsWith('/app/') ? '' : 'http://localhost:8000');
export const START_PARCEL = query.get('parcel');

export async function api(path, options) {
  const response = await fetch(API + path, options);
  if (!response.ok) throw new Error('HTTP ' + response.status);
  return response.json();
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
