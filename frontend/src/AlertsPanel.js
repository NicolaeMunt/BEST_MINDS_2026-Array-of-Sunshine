// "Alerte": every field's alerts in one list, newest first, with a filter for high (red) and medium (yellow) risk.
import { html, useState, useEffect, api, num, hm, day } from './lib.js';
import { alertWord } from './labels.js';

const FILTERS = [['all', 'Toate'], ['critical', 'Risc mare'], ['warning', 'Risc mediu']];
const PERIODS = [[7, 'ultimele 7 zile'], [30, 'ultimele 30 de zile'], [null, 'tot sezonul']];

function facts(a) {
  // The soil probe's advice has no deficit, only the moisture in its message.
  if (a.type === 'IRRIGATION') return a.deficitMm != null ? `lipsesc ${num(a.deficitMm, 0)} mm de apă în sol` : 'solul e prea uscat';
  if (a.type === 'SOWING') return `solul are ${num(a.temperatureC)}°C la 5 cm`;
  return `${num(a.temperatureC)}°C, umiditate ${num(a.humidityPct, 0)}%`;
}

export function AlertsPanel({ sensors, onSelect, reload }) {
  const [alerts, setAlerts] = useState([]);
  const [filter, setFilter] = useState('all');
  const [period, setPeriod] = useState(0);

  useEffect(() => {
    let stopped = false, timer;
    const load = () => api('/alerts?type=ALL')
      .then(a => { if (!stopped) setAlerts(a); }).catch(() => {})
      .finally(() => { if (!stopped) timer = setTimeout(load, 15000); });
    load();
    return () => { stopped = true; clearTimeout(timer); };
  }, [reload]);

  const [days, periodLabel] = PERIODS[period];
  const since = days ? Date.now() - days * 86400000 : 0;
  // The all-clear messages are left out: the list is what needs (or needed) the farmer's attention.
  const shown = alerts.filter(a => a.level !== 'OK' && Date.parse(a.timestamp) >= since)
    .filter(a => filter === 'all' || alertWord(a).status === filter);
  const count = status => alerts.filter(a => a.level !== 'OK' && Date.parse(a.timestamp) >= since
    && alertWord(a).status === status).length;

  return html`<section className="alerts-panel" aria-labelledby="alerts-title">
    <h2 id="alerts-title">Alerte</h2>
    <div className="filters" role="group" aria-label="Ce alerte arăt">
      ${FILTERS.map(([key, label]) => html`<button key=${key} aria-pressed=${filter === key}
          className=${key === 'all' ? '' : 'is-' + key} onClick=${() => setFilter(key)}>
        ${key !== 'all' && html`<i className="dot"></i>`}${label}${key !== 'all' ? ` (${count(key)})` : ''}</button>`)}
    </div>
    <p className="note">Pe toate terenurile, din ${periodLabel}.</p>
    ${shown.length === 0
      ? html`<p className="alerts-empty">Nicio alertă${filter === 'all' ? '' : ' de acest fel'}. Alertele ajung și pe Telegram.</p>`
      : html`<ul className="alert-list">
        ${shown.map(a => html`<li key=${a.parcelId + a.timestamp + a.type + a.level}>
          <button className=${'alert-item is-' + alertWord(a).status} onClick=${() => onSelect(a.parcelId)}>
            <span className="alert-head"><span className="stamp">${alertWord(a).word}</span>
              <time>${day(a.timestamp, false)}, ${hm(new Date(a.timestamp))}</time></span>
            <span className="alert-field">${a.parcelName}</span>
            <span className="alert-facts">${facts(a)}</span>
          </button>
        </li>`)}
      </ul>`}
    ${period < PERIODS.length - 1 && html`<button className="btn btn-small more" onClick=${() => setPeriod(period + 1)}>
      Arată mai vechi</button>`}
  </section>`;
}
