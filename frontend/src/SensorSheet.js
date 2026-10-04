// One field: what it needs now, the air and the soil, what the satellite sees, the soil water and the temperature.
import { html, useState, useEffect, api, num, hm, when, day } from './lib.js';
import { MODE, verdict, alertWord, phaseLine } from './labels.js';
import { SatelliteSection } from './SatelliteSection.js';

// [minutes, button label, how the alert list and the statistics name the period]
const RANGES = [[60, 'O oră', 'din ultima oră', 'Ultima oră'], [1440, 'O zi', 'din ultima zi', 'Ultima zi'],
  [10080, 'O săptămână', 'din ultima săptămână', 'Ultima săptămână'], [43200, 'O lună', 'din ultima lună', 'Ultima lună']];
const W = 760, H = 300, LEFT = 44, RIGHT = 56, TOP = 26, BOTTOM = 30;

/** Marks along the time axis: month starts for a season, midnights for a week, nothing for shorter charts. */
function timeMarks(t0, t1, minutes) {
  const marks = [];
  if (minutes <= 1440) return marks;
  const byMonth = minutes > 20160, d = new Date(t0);
  d.setHours(0, 0, 0, 0);
  if (byMonth) d.setDate(1);
  while (d.getTime() <= t1) {
    if (d.getTime() > t0) marks.push([d.getTime(), d.toLocaleDateString('ro-RO', byMonth ? { month: 'long' } : { weekday: 'short', day: 'numeric' })]);
    if (byMonth) d.setMonth(d.getMonth() + 1); else d.setDate(d.getDate() + 1);
  }
  return marks;
}

function TempChart({ readings, minutes, alerts }) {
  if (readings.length < 2) return html`<p className="note">Încă nu sunt destule măsurători pentru grafic. Apar în câteva secunde.</p>`;
  // Long charts show, for every hour or day, the range between its lowest and highest temperature.
  const banded = minutes > 1440;
  const t1 = Date.parse(readings[readings.length - 1].timestamp), t0 = t1 - minutes * 60000;
  const values = readings.flatMap(r => banded ? [r.minTemperatureC, r.maxTemperatureC] : [r.temperatureC]);
  const lo = Math.floor(Math.min(...values, 0) - 1), hi = Math.ceil(Math.max(...values) + 1);
  const x = t => LEFT + (W - LEFT - RIGHT) * Math.max(0, Math.min(1, (t - t0) / (t1 - t0)));
  const y = c => TOP + (H - TOP - BOTTOM) * (hi - c) / (hi - lo);
  const at = r => x(Date.parse(r.timestamp)).toFixed(1);
  const line = readings.map((r, i) => (i ? 'L' : 'M') + at(r) + ' ' + y(r.temperatureC).toFixed(1)).join('');
  const band = banded && readings.map(r => at(r) + ',' + y(r.maxTemperatureC).toFixed(1)).join(' ') + ' ' +
    [...readings].reverse().map(r => at(r) + ',' + y(r.minTemperatureC).toFixed(1)).join(' ');
  const every = Math.max(1, Math.ceil((hi - lo) / 4)), ticks = [];
  for (let c = Math.ceil(lo / every) * every; c <= hi; c += every) ticks.push(c);
  const last = readings[readings.length - 1];
  const marks = timeMarks(t0, t1, minutes);
  const edge = t => minutes > 60 ? when(new Date(t).toISOString()) : hm(new Date(t));
  // Urgent alerts are drawn last, so a warning sent the same night does not cover them.
  const flags = alerts.filter(a => Date.parse(a.timestamp) >= t0 && Date.parse(a.timestamp) <= t1)
    .sort((a, b) => (a.level === 'CRITICAL') - (b.level === 'CRITICAL'));
  return html`<svg className="temp-chart" viewBox=${`0 0 ${W} ${H}`} role="img"
      aria-label=${`Temperatura aerului în timp, cu ${flags.length} alerte marcate`}>
    <rect className="below-zero" x=${LEFT} y=${y(0)} width=${W - LEFT - RIGHT} height=${H - BOTTOM - y(0)} />
    ${ticks.map(c => html`<g key=${c}>
      <line className=${c === 0 ? 'zero' : 'grid'} x1=${LEFT} x2=${W - RIGHT} y1=${y(c)} y2=${y(c)} />
      <text className="tick" x=${LEFT - 8} y=${y(c) + 5} textAnchor="end">${c}°</text></g>`)}
    ${marks.map(([t, label]) => html`<g key=${t}>
      <line className="grid" x1=${x(t)} x2=${x(t)} y1=${TOP} y2=${H - BOTTOM} />
      <text className="tick" x=${x(t) + 4} y=${H - 8}>${label}</text></g>`)}
    ${banded && html`<polygon className="temp-band" points=${band} />`}
    <path className=${banded ? 'temp-line temp-line-thin' : 'temp-line'} d=${line} />
    ${flags.map((a, i) => html`<g key=${i} className=${'flag is-' + alertWord(a).status}>
      <title>${when(a.timestamp)}: ${alertWord(a).word}</title>
      <line x1=${x(Date.parse(a.timestamp))} x2=${x(Date.parse(a.timestamp))} y1=${TOP - 8} y2=${TOP + 6} />
      <rect x=${x(Date.parse(a.timestamp)) - 6} y=${TOP - 20} width="12" height="12" /></g>`)}
    <circle className="temp-now" cx=${x(t1)} cy=${y(last.temperatureC)} r="5" />
    <text className="now" x=${x(t1) + 8} y=${y(last.temperatureC) + 6}>${num(last.temperatureC)}°</text>
    ${marks.length === 0 && html`<text className="tick" x=${LEFT} y=${H - 8}>${edge(t0)}</text>`}
    ${marks.length === 0 && html`<text className="tick" x=${W - RIGHT} y=${H - 8} textAnchor="end">${edge(t1)}</text>`}
  </svg>`;
}

// Simple line icons for the two cards: a cloud for the air, a sprout in the soil for the ground.
const AIR_ICON = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 18h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.1 10 4 4 0 0 0 7 18z"/></svg>`;
const SOIL_ICON = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14V8"/><path d="M12 10c0-3 2-5 5-5 0 3-2 5-5 5z"/><path d="M12 11C12 8.5 10.3 7 8 7c0 2.3 1.7 4 4 4z"/><path d="M3 14h18M5 18h14M8 21h8"/></svg>`;

/** The period's lowest, mean and highest temperature and air humidity, as two cards a farmer reads at a glance. */
function PeriodStats({ sensorId, minutes }) {
  const [stats, setStats] = useState([]);
  useEffect(() => {
    let stopped = false, timer;
    const load = () => api('/sensors/parcels/' + encodeURIComponent(sensorId) + '/stats')
      .then(s => { if (!stopped) setStats(s); }).catch(() => {})
      .finally(() => { if (!stopped) timer = setTimeout(load, 30000); });
    load();
    return () => { stopped = true; clearTimeout(timer); };
  }, [sensorId]);
  const s = stats.find(x => x.minutes === minutes);
  if (!s || !s.readings) return null;
  const card = (title, unit, lo, mean, hi, loWord, hiWord) => html`<div className="stat-card">
    <h3>${title}</h3>
    <div className="stat-row">
      <div className="stat stat-lo"><b>${num(lo, unit === '%' ? 0 : 1)}<small>${unit}</small></b><span>${loWord}</span></div>
      <div className="stat stat-mean"><b>${num(mean, unit === '%' ? 0 : 1)}<small>${unit}</small></b><span>în medie</span></div>
      <div className="stat stat-hi"><b>${num(hi, unit === '%' ? 0 : 1)}<small>${unit}</small></b><span>${hiWord}</span></div>
    </div>
  </div>`;
  return html`<div className="stat-cards">
    ${card('Temperatura', '°', s.minC, s.meanC, s.maxC, 'cea mai rece', 'cea mai caldă')}
    ${card('Umiditatea aerului', '%', s.minHumidityPct, s.meanHumidityPct, s.maxHumidityPct, 'cea mai uscată', 'cea mai umedă')}
  </div>`;
}

export function SensorSheet({ sensor, readings, minutes, onMinutes, alerts, parcel, history }) {
  const s = sensor.latest, v = verdict(sensor), drop = s && s.dropLastHourC;
  const trend = drop == null ? '' : drop > 0.3 ? `Se răcește: cu ${num(drop)}° mai rece decât acum o oră.`
    : drop < -0.3 ? `Se încălzește: cu ${num(-drop)}° mai cald decât acum o oră.` : 'Temperatura stă pe loc față de acum o oră.';
  const sent = alerts.filter(a => a.level !== 'OK');  // marked on the chart; the all-clear messages are left out
  const banded = minutes > 1440;
  return html`
    <section className=${'verdict is-' + v.status}>
      <div className="verdict-main">
        <h2>${v.title}</h2>
        <p>${v.text}</p>
        ${s && html`<p className="verdict-more">${trend}${phaseLine(s) ? ' ' + phaseLine(s) : ''}</p>`}
      </div>
      ${s && html`<div className="verdict-temp"><b>${num(s.temperatureC)}°</b><span>acum</span></div>`}
    </section>
    ${s && MODE[s.mode] && html`<p className="note demo-note">Demonstrație: senzorul arată ${MODE[s.mode]}, nu vremea de afară.</p>`}

    ${s && html`<section className="section">
      <h2>Acum</h2>
      <div className="cards">
        <div className="card">
          <h3>${AIR_ICON}Aerul</h3>
          <div className="figures">
            <div className="figure"><b>${num(s.temperatureC)}<small>°C</small></b><span>temperatura</span></div>
            <div className="figure"><b>${num(s.humidityPct, 0)}<small>%</small></b><span>umiditatea</span></div>
          </div>
        </div>
        ${s.soilMoisturePct != null && html`<div className="card">
          <h3>${SOIL_ICON}Solul</h3>
          <div className="figures">
            <div className="figure"><b>${num(s.soilTemperatureC)}<small>°C</small></b><span>temperatura la 5 cm</span></div>
            <div className="figure"><b>${num(s.soilMoisturePct, 0)}<small>%</small></b><span>apă la 20 cm</span></div>
          </div>
        </div>`}
      </div>
      <p className="note updated">Actualizat ${when(s.timestamp)}</p>
    </section>`}

    ${parcel && history && html`<${SatelliteSection} parcel=${parcel} history=${history} />`}

    <section className="section">
      <h2>Vremea pe teren</h2>
      <div className="ranges" role="group" aria-label="Ce perioadă arăt">
        ${RANGES.map(([value, , , label]) => html`<button key=${value} aria-pressed=${minutes === value}
          onClick=${() => onMinutes(value)}>${label}</button>`)}
      </div>
      <${PeriodStats} sensorId=${sensor.id} minutes=${minutes} />
      <h3 className="chart-title">Temperatura în timp</h3>
      <${TempChart} readings=${readings} minutes=${minutes} alerts=${sent} />
      <p className="legend">
        ${banded && html`<span><i className="key key-band"></i>de la cea mai rece la cea mai caldă oră ${minutes > 20160 ? 'a zilei' : ''}</span>`}
        <span><i className="key key-zero"></i>sub zero: îngheț</span>
        <span><i className="key key-flag is-warning"></i><i className="key key-flag is-critical"></i>alertă</span>
      </p>
    </section>`;
}
