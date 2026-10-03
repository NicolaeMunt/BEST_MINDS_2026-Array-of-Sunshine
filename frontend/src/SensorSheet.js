// One sensor: what it means right now, the numbers, the temperature over time, the alerts sent.
import { html, num, hm, when } from './lib.js';
import { MODE, ALERT_STATUS, verdict } from './labels.js';

const RANGES = [[15, '15 minute'], [60, 'o oră'], [720, '12 ore'], [1440, '24 de ore']];
const W = 760, H = 280, LEFT = 40, RIGHT = 52, TOP = 12, BOTTOM = 28;

function Figure({ label, value, unit, hint }) {
  return html`<div className="figure"><b>${value}<small>${unit}</small></b><span>${label}</span>
    ${hint && html`<span className="hint">${hint}</span>`}</div>`;
}

function TempChart({ readings, minutes }) {
  if (readings.length < 2) return html`<p className="note">Încă nu sunt destule citiri pentru grafic. Apar în câteva secunde.</p>`;
  const t1 = Date.parse(readings[readings.length - 1].timestamp), t0 = t1 - minutes * 60000;
  const values = readings.flatMap(r => [r.temperatureC, r.dewPointC]);
  const lo = Math.floor(Math.min(...values, 0) - 1), hi = Math.ceil(Math.max(...values) + 1);
  const x = t => LEFT + (W - LEFT - RIGHT) * Math.max(0, Math.min(1, (t - t0) / (t1 - t0)));
  const y = c => TOP + (H - TOP - BOTTOM) * (hi - c) / (hi - lo);
  const path = key => readings.map((r, i) => (i ? 'L' : 'M') + x(Date.parse(r.timestamp)).toFixed(1) + ' ' + y(r[key]).toFixed(1)).join('');
  const every = Math.max(1, Math.ceil((hi - lo) / 5)), ticks = [];
  for (let c = Math.ceil(lo / every) * every; c <= hi; c += every) ticks.push(c);
  const last = readings[readings.length - 1], lx = x(t1);
  const edge = t => minutes > 60 ? when(new Date(t).toISOString()) : hm(new Date(t));
  return html`<svg className="temp-chart" viewBox=${`0 0 ${W} ${H}`} role="img"
      aria-label="Temperatura aerului și punctul de rouă în timp">
    <rect className="below-zero" x=${LEFT} y=${y(0)} width=${W - LEFT - RIGHT} height=${H - BOTTOM - y(0)} />
    ${ticks.map(c => html`<g key=${c}>
      <line className=${c === 0 ? 'zero' : 'grid'} x1=${LEFT} x2=${W - RIGHT} y1=${y(c)} y2=${y(c)} />
      <text className="tick" x=${LEFT - 8} y=${y(c) + 4} textAnchor="end">${c}°</text></g>`)}
    <path className="dew-line" d=${path('dewPointC')} />
    <path className="temp-line" d=${path('temperatureC')} />
    <circle className="temp-now" cx=${lx} cy=${y(last.temperatureC)} r="5" />
    <text className="now" x=${lx + 8} y=${y(last.temperatureC) + 5}>${num(last.temperatureC)}°</text>
    <text className="tick" x=${LEFT} y=${H - 8}>${edge(t0)}</text>
    <text className="tick" x=${W - RIGHT} y=${H - 8} textAnchor="end">${edge(t1)}</text>
  </svg>`;
}

export function SensorSheet({ sensor, readings, minutes, onMinutes, alerts }) {
  const s = sensor.latest, v = verdict(sensor), drop = s && s.dropLastHourC;
  const trend = drop == null ? '' : drop > 0.3 ? `E cu ${num(drop)}°C mai rece decât acum o oră.`
    : drop < -0.3 ? `E cu ${num(-drop)}°C mai cald decât acum o oră.` : 'Temperatura e la fel ca acum o oră.';
  return html`
    <section className=${'today is-' + v.status}>
      <span className="stamp">${v.word}</span>
      <h2>${v.title}</h2>
      <p>${v.text}</p>
      ${s && s.frost.reasons.length > 0 && html`<ul className="why">
        ${s.frost.reasons.map(r => html`<li key=${r.code}>${r.text}.</li>`)}</ul>`}
      ${s && MODE[s.mode] && html`<p className="note">Demonstrație: senzorul arată ${MODE[s.mode]}, nu vremea de afară.</p>`}
    </section>

    ${s && html`<section className="section">
      <h2>Acum</h2>
      <div className="figures">
        <${Figure} label="Temperatura aerului" value=${num(s.temperatureC)} unit="°C" />
        <${Figure} label="Umiditatea aerului" value=${num(s.humidityPct, 0)} unit="%" />
        <${Figure} label="Punctul de rouă" value=${num(s.dewPointC)} unit="°C"
                   hint="Dacă aerul se răcește până aici, apare roua sau, sub zero, bruma." />
      </div>
      <p>${trend}</p>
      <p className="note">Ultima citire: ${when(s.timestamp)}.</p>
    </section>`}

    <section className="section">
      <div className="chart-head">
        <h2>Temperatura în timp</h2>
        <div className="ranges" role="group" aria-label="Cât timp arată graficul">
          ${RANGES.map(([value, label]) => html`<button key=${value} aria-pressed=${minutes === value}
            onClick=${() => onMinutes(value)}>${label}</button>`)}
        </div>
      </div>
      <${TempChart} readings=${readings} minutes=${minutes} />
      <p className="legend">
        <span><i className="key key-temp"></i>temperatura aerului</span>
        <span><i className="key key-dew"></i>punctul de rouă</span>
        <span><i className="key key-zero"></i>sub 0°C, îngheț</span>
      </p>
    </section>

    <section className="section">
      <h2>Alerte trimise</h2>
      ${alerts.length === 0
        ? html`<p className="note">Nicio alertă pentru ${sensor.name}. Când e risc de îngheț sau aerul devine prea umed
            ori prea uscat, alerta apare aici și pe Telegram.</p>`
        : html`<ul className="alerts">
          ${alerts.map((a, i) => html`<li key=${i} className=${'is-' + (a.level === 'OK' ? 'ok' : ALERT_STATUS[a.priority])}>
            <div className="alert-head">
              <span className="stamp">${a.title}</span>
              <time>${when(a.timestamp)}</time>
            </div>
            <p className="alert-text">${a.message}</p>
          </li>`)}
        </ul>`}
    </section>`;
}
