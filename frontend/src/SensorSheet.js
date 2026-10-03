// One sensor: what it means right now, the numbers, the temperature over time with its alerts.
import { html, useState, num, hm, when, day } from './lib.js';
import { MODE, ALERT_STATUS, verdict } from './labels.js';

// Minutes since 1 May of this year: the whole season on one chart.
const SEASON = Math.ceil((Date.now() - new Date(new Date().getFullYear(), 4, 1)) / 60000);
// [minutes, button label, how the alert list names the period]
const RANGES = [[15, '15 minute', 'din ultimele 15 minute'], [1440, '24 de ore', 'din ultimele 24 de ore'],
  [10080, '7 zile', 'din ultimele 7 zile'], [SEASON, 'din mai', 'din mai până azi']];
const SHOWN_ALERTS = 6;
const W = 760, H = 300, LEFT = 40, RIGHT = 52, TOP = 26, BOTTOM = 28;

function Figure({ label, value, unit, hint }) {
  return html`<div className="figure"><b>${value}<small>${unit}</small></b><span>${label}</span>
    ${hint && html`<span className="hint">${hint}</span>`}</div>`;
}

/** Marks along the time axis: month starts for a season, midnights for a week, nothing for shorter charts. */
function timeMarks(t0, t1, minutes) {
  const marks = [];
  if (minutes <= 1440) return marks;
  const byMonth = minutes > 20160, d = new Date(t0);
  d.setHours(0, 0, 0, 0);
  if (byMonth) d.setDate(1);
  while (d.getTime() <= t1) {
    if (d.getTime() > t0) marks.push([d.getTime(), d.toLocaleDateString('ro-RO', byMonth ? { month: 'long' } : { day: 'numeric', month: 'short' })]);
    if (byMonth) d.setMonth(d.getMonth() + 1); else d.setDate(d.getDate() + 1);
  }
  return marks;
}

function TempChart({ readings, minutes, alerts }) {
  if (readings.length < 2) return html`<p className="note">Încă nu sunt destule citiri pentru grafic. Apar în câteva secunde.</p>`;
  // Long charts show, for every hour or day, the range between its lowest and highest temperature.
  const banded = minutes > 1440;
  const t1 = Date.parse(readings[readings.length - 1].timestamp), t0 = t1 - minutes * 60000;
  const values = readings.flatMap(r => banded ? [r.minTemperatureC, r.maxTemperatureC] : [r.temperatureC, r.dewPointC]);
  const lo = Math.floor(Math.min(...values, 0) - 1), hi = Math.ceil(Math.max(...values) + 1);
  const x = t => LEFT + (W - LEFT - RIGHT) * Math.max(0, Math.min(1, (t - t0) / (t1 - t0)));
  const y = c => TOP + (H - TOP - BOTTOM) * (hi - c) / (hi - lo);
  const at = r => x(Date.parse(r.timestamp)).toFixed(1);
  const path = key => readings.map((r, i) => (i ? 'L' : 'M') + at(r) + ' ' + y(r[key]).toFixed(1)).join('');
  const band = banded && readings.map(r => at(r) + ',' + y(r.maxTemperatureC).toFixed(1)).join(' ') + ' ' +
    [...readings].reverse().map(r => at(r) + ',' + y(r.minTemperatureC).toFixed(1)).join(' ');
  const every = Math.max(1, Math.ceil((hi - lo) / 5)), ticks = [];
  for (let c = Math.ceil(lo / every) * every; c <= hi; c += every) ticks.push(c);
  const last = readings[readings.length - 1];
  const marks = timeMarks(t0, t1, minutes);
  const edge = t => minutes > 60 ? when(new Date(t).toISOString()) : hm(new Date(t));
  // Urgent alerts are drawn last, so a warning sent the same night does not cover them.
  const flags = alerts.filter(a => a.level !== 'OK' && Date.parse(a.timestamp) >= t0 && Date.parse(a.timestamp) <= t1)
    .sort((a, b) => (a.priority === 'high') - (b.priority === 'high'));
  return html`<svg className="temp-chart" viewBox=${`0 0 ${W} ${H}`} role="img"
      aria-label=${`Temperatura aerului în timp, cu ${flags.length} alerte marcate`}>
    <rect className="below-zero" x=${LEFT} y=${y(0)} width=${W - LEFT - RIGHT} height=${H - BOTTOM - y(0)} />
    ${ticks.map(c => html`<g key=${c}>
      <line className=${c === 0 ? 'zero' : 'grid'} x1=${LEFT} x2=${W - RIGHT} y1=${y(c)} y2=${y(c)} />
      <text className="tick" x=${LEFT - 8} y=${y(c) + 4} textAnchor="end">${c}°</text></g>`)}
    ${marks.map(([t, label]) => html`<g key=${t}>
      <line className="grid" x1=${x(t)} x2=${x(t)} y1=${TOP} y2=${H - BOTTOM} />
      <text className="tick" x=${x(t) + 4} y=${H - 8}>${label}</text></g>`)}
    ${banded ? html`<polygon className="temp-band" points=${band} />` : html`<path className="dew-line" d=${path('dewPointC')} />`}
    <path className=${banded ? 'temp-line temp-line-thin' : 'temp-line'} d=${path('temperatureC')} />
    ${flags.map((a, i) => html`<g key=${i} className=${'flag is-' + ALERT_STATUS[a.priority]}>
      <title>${when(a.timestamp)}: ${a.title}</title>
      <line x1=${x(Date.parse(a.timestamp))} x2=${x(Date.parse(a.timestamp))} y1=${TOP - 8} y2=${TOP + 6} />
      <rect x=${x(Date.parse(a.timestamp)) - 5} y=${TOP - 18} width="10" height="10" /></g>`)}
    <circle className="temp-now" cx=${x(t1)} cy=${y(last.temperatureC)} r="5" />
    <text className="now" x=${x(t1) + 8} y=${y(last.temperatureC) + 5}>${num(last.temperatureC)}°</text>
    ${marks.length === 0 && html`<text className="tick" x=${LEFT} y=${H - 8}>${edge(t0)}</text>`}
    ${marks.length === 0 && html`<text className="tick" x=${W - RIGHT} y=${H - 8} textAnchor="end">${edge(t1)}</text>`}
  </svg>`;
}

export function SensorSheet({ sensor, readings, minutes, onMinutes, alerts }) {
  const s = sensor.latest, v = verdict(sensor), drop = s && s.dropLastHourC;
  const trend = drop == null ? '' : drop > 0.3 ? `E cu ${num(drop)}°C mai rece decât acum o oră.`
    : drop < -0.3 ? `E cu ${num(-drop)}°C mai cald decât acum o oră.` : 'Temperatura e la fel ca acum o oră.';
  const range = RANGES.find(r => r[0] === minutes) || RANGES[1];
  // The list follows the chart's period. It counts back from now, so alerts show during a replayed night too.
  const inPeriod = alerts.filter(a => Date.parse(a.timestamp) >= Date.now() - minutes * 60000);
  const [showAll, setShowAll] = useState(false);
  const listed = showAll ? inPeriod : inPeriod.slice(0, SHOWN_ALERTS);
  const banded = minutes > 1440;
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
            onClick=${() => { setShowAll(false); onMinutes(value); }}>${label}</button>`)}
        </div>
      </div>
      <${TempChart} readings=${readings} minutes=${minutes} alerts=${alerts} />
      <p className="legend">
        ${banded
          ? html`<span><i className="key key-band"></i>între cea mai mică și cea mai mare temperatură ${minutes > 20160 ? 'a zilei' : 'a orei'}</span>`
          : html`<span><i className="key key-temp"></i>temperatura aerului</span>`}
        ${!banded && html`<span><i className="key key-dew"></i>punctul de rouă</span>`}
        <span><i className="key key-zero"></i>sub 0°C, îngheț</span>
        <span><i className="key key-flag is-warning"></i>alertă: cere atenție</span>
        <span><i className="key key-flag is-critical"></i>alertă: urgent</span>
      </p>
    </section>

    <section className="section">
      <h2>Alerte ${range[2]}</h2>
      ${inPeriod.length === 0
        ? html`<p className="note">Nicio alertă pentru ${sensor.name} în această perioadă. Când e risc de îngheț sau aerul
            devine prea umed ori prea uscat, alerta apare aici și pe Telegram.</p>`
        : html`<ul className="alerts">
          ${listed.map(a => html`<li key=${a.timestamp + a.type + a.level} className=${'is-' + (a.level === 'OK' ? 'ok' : ALERT_STATUS[a.priority])}>
            <div className="alert-head">
              <span className="stamp">${a.title}</span>
              <time>${day(a.timestamp, false)}, ${hm(new Date(a.timestamp))}</time>
            </div>
            <p className="alert-text">${a.message}</p>
          </li>`)}
        </ul>`}
      ${inPeriod.length > listed.length && html`<button className="btn more" onClick=${() => setShowAll(true)}>
        Arată toate cele ${inPeriod.length} alerte</button>`}
    </section>`;
}
