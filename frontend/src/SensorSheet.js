// One field: what it needs now, the air and the soil, what the satellite sees, the soil water and the temperature.
import { html, useState, useEffect, api, num, hm, when, day } from './lib.js';
import { MODE, verdict, alertWord, phaseLine } from './labels.js';
import { SatelliteSection } from './SatelliteSection.js';

// [minutes, button label, how the alert list and the statistics name the period]
const RANGES = [[60, 'O oră', 'din ultima oră', 'Ultima oră'], [1440, 'O zi', 'din ultima zi', 'Ultima zi'],
  [10080, 'O săptămână', 'din ultima săptămână', 'Ultima săptămână'], [43200, 'O lună', 'din ultima lună', 'Ultima lună']];
const W = 760, H = 300, LEFT = 44, RIGHT = 56, TOP = 26, BOTTOM = 30;
// What the weather chart can show. zone: the part of the scale that means danger, shaded (frost, damp air).
const METRICS = {
  temp: { value: 'temperatureC', min: 'minTemperatureC', max: 'maxTemperatureC', unit: '°', name: 'Temperatura aerului',
    zone: { below: 0, className: 'below-zero' } },
  hum: { value: 'humidityPct', min: 'minHumidityPct', max: 'maxHumidityPct', unit: '%', name: 'Umiditatea aerului',
    zone: { above: 90, className: 'humid-zone' }, scale: [0, 100] },
};

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

function WeatherChart({ readings, minutes, alerts, drawKey, metric }) {
  if (readings.length < 2) return html`<p className="note">Încă nu sunt destule măsurători pentru grafic. Apar în câteva secunde.</p>`;
  const m = METRICS[metric], val = r => r[m.value];
  // Long charts show, for every hour or day, the range between its lowest and highest value.
  const banded = minutes > 1440 && readings.every(r => r[m.min] != null);
  const t1 = Date.parse(readings[readings.length - 1].timestamp), t0 = t1 - minutes * 60000;
  const values = readings.flatMap(r => banded ? [r[m.min], r[m.max]] : [val(r)]);
  // Temperature keeps 0 in view (frost); humidity stays within 0-100 %.
  let lo = Math.floor(Math.min(...values, m.zone.below ?? Infinity) - 1), hi = Math.ceil(Math.max(...values) + 1);
  if (m.scale) { lo = Math.max(m.scale[0], lo - 4); hi = Math.min(m.scale[1], Math.max(hi + 4, m.zone.above + 2)); }
  const x = t => LEFT + (W - LEFT - RIGHT) * Math.max(0, Math.min(1, (t - t0) / (t1 - t0)));
  const y = c => TOP + (H - TOP - BOTTOM) * (hi - c) / (hi - lo);
  const at = r => x(Date.parse(r.timestamp)).toFixed(1);
  const line = readings.map((r, i) => (i ? 'L' : 'M') + at(r) + ' ' + y(val(r)).toFixed(1)).join('');
  const band = banded && readings.map(r => at(r) + ',' + y(r[m.max]).toFixed(1)).join(' ') + ' ' +
    [...readings].reverse().map(r => at(r) + ',' + y(r[m.min]).toFixed(1)).join(' ');
  const zone = m.zone.below != null ? [y(m.zone.below), H - BOTTOM] : [TOP, y(Math.min(hi, m.zone.above))];
  const every = Math.max(1, Math.ceil((hi - lo) / 4 / (m.scale ? 5 : 1)) * (m.scale ? 5 : 1)), ticks = [];
  for (let c = Math.ceil(lo / every) * every; c <= hi; c += every) ticks.push(c);
  const last = readings[readings.length - 1];
  const marks = timeMarks(t0, t1, minutes);
  const edge = t => minutes > 60 ? when(new Date(t).toISOString()) : hm(new Date(t));
  // Urgent alerts are drawn last, so a warning sent the same night does not cover them.
  const flags = alerts.filter(a => Date.parse(a.timestamp) >= t0 && Date.parse(a.timestamp) <= t1)
    .sort((a, b) => (a.level === 'CRITICAL') - (b.level === 'CRITICAL'));
  // drawKey changes with the sensor and the period, so the line draws itself again only then, not on every refresh.
  return html`<svg key=${drawKey + metric} className="temp-chart" viewBox=${`0 0 ${W} ${H}`} role="img"
      aria-label=${`${m.name} în timp, cu ${flags.length} alerte marcate`}>
    ${zone[1] > zone[0] && html`<rect className=${m.zone.className} x=${LEFT} y=${zone[0]} width=${W - LEFT - RIGHT} height=${zone[1] - zone[0]} />`}
    ${ticks.map(c => html`<g key=${c}>
      <line className=${c === 0 && m.zone.below === 0 ? 'zero' : 'grid'} x1=${LEFT} x2=${W - RIGHT} y1=${y(c)} y2=${y(c)} />
      <text className="tick" x=${LEFT - 8} y=${y(c) + 5} textAnchor="end">${c}${m.unit}</text></g>`)}
    ${marks.map(([t, label]) => html`<g key=${t}>
      <line className="grid" x1=${x(t)} x2=${x(t)} y1=${TOP} y2=${H - BOTTOM} />
      <text className="tick" x=${x(t) + 4} y=${H - 8}>${label}</text></g>`)}
    ${banded && html`<polygon className="temp-band" points=${band} />`}
    <path className=${banded ? 'temp-line temp-line-thin' : 'temp-line'} d=${line} pathLength="1" />
    ${flags.map((a, i) => html`<g key=${i} className=${'flag is-' + alertWord(a).status}>
      <title>${when(a.timestamp)}: ${alertWord(a).word}</title>
      <line x1=${x(Date.parse(a.timestamp))} x2=${x(Date.parse(a.timestamp))} y1=${TOP - 8} y2=${TOP + 6} />
      <rect x=${x(Date.parse(a.timestamp)) - 6} y=${TOP - 20} width="12" height="12" /></g>`)}
    <circle className="temp-now" cx=${x(t1)} cy=${y(val(last))} r="5" />
    <text className="now" x=${x(t1) + 8} y=${y(val(last)) + 6}>${num(val(last), m.unit === '%' ? 0 : 1)}${m.unit}</text>
    ${marks.length === 0 && html`<text className="tick" x=${LEFT} y=${H - 8}>${edge(t0)}</text>`}
    ${marks.length === 0 && html`<text className="tick" x=${W - RIGHT} y=${H - 8} textAnchor="end">${edge(t1)}</text>`}
  </svg>`;
}

// Simple line icons for the two cards: a cloud for the air, a sprout in the soil for the ground.
const AIR_ICON = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 18h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.1 10 4 4 0 0 0 7 18z"/></svg>`;
const SOIL_ICON = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14V8"/><path d="M12 10c0-3 2-5 5-5 0 3-2 5-5 5z"/><path d="M12 11C12 8.5 10.3 7 8 7c0 2.3 1.7 4 4 4z"/><path d="M3 14h18M5 18h14M8 21h8"/></svg>`;

/** The period's lowest, mean and highest temperature and air humidity, as two cards a farmer reads at a glance. */
function PeriodStats({ sensorId, minutes, metric, onMetric }) {
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
  const card = (key, title, unit, lo, mean, hi, loWord, hiWord) => html`<button type="button" className="stat-card"
      aria-pressed=${metric === key} onClick=${() => onMetric(key)} title=${'Arată pe grafic: ' + title.toLowerCase()}>
    <h3>${title}<span className="stat-pick" aria-hidden="true">${metric === key ? 'pe grafic' : 'vezi graficul'}</span></h3>
    <div className="stat-row">
      <div className="stat stat-lo"><b>${num(lo, unit === '%' ? 0 : 1)}<small>${unit}</small></b><span>${loWord}</span></div>
      <div className="stat stat-mean"><b>${num(mean, unit === '%' ? 0 : 1)}<small>${unit}</small></b><span>în medie</span></div>
      <div className="stat stat-hi"><b>${num(hi, unit === '%' ? 0 : 1)}<small>${unit}</small></b><span>${hiWord}</span></div>
    </div>
  </button>`;
  return html`<div className="stat-cards">
    ${card('temp', 'Temperatura', '°', s.minC, s.meanC, s.maxC, 'cea mai rece', 'cea mai caldă')}
    ${card('hum', 'Umiditatea aerului', '%', s.minHumidityPct, s.meanHumidityPct, s.maxHumidityPct, 'cea mai uscată', 'cea mai umedă')}
  </div>`;
}

export function SensorSheet({ sensor, readings, minutes, onMinutes, alerts, drawKey, parcel, history }) {
  const s = sensor.latest, v = verdict(sensor), drop = s && s.dropLastHourC;
  const trend = drop == null ? '' : drop > 0.3 ? `Se răcește: cu ${num(drop)}° mai rece decât acum o oră.`
    : drop < -0.3 ? `Se încălzește: cu ${num(-drop)}° mai cald decât acum o oră.` : 'Temperatura stă pe loc față de acum o oră.';
  const sent = alerts.filter(a => a.level !== 'OK');  // marked on the chart; the all-clear messages are left out
  const banded = minutes > 1440;
  const [metric, setMetric] = useState('temp');  // what the weather chart shows: temp | hum
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
      <${PeriodStats} sensorId=${sensor.id} minutes=${minutes} metric=${metric} onMetric=${setMetric} />
      <h3 className="chart-title">${METRICS[metric].name} în timp</h3>
      <${WeatherChart} readings=${readings} minutes=${minutes} alerts=${sent} drawKey=${drawKey} metric=${metric} />
      <p className="legend">
        ${banded && html`<span><i className="key key-band"></i>${metric === 'temp'
          ? 'de la cea mai rece la cea mai caldă oră' : 'de la cea mai uscată la cea mai umedă oră'} ${minutes > 20160 ? 'a zilei' : ''}</span>`}
        ${metric === 'temp' ? html`<span><i className="key key-zero"></i>sub zero: îngheț</span>`
          : html`<span><i className="key key-humid"></i>peste 90%: aer umed, risc de boală</span>`}
        <span><i className="key key-flag is-warning"></i><i className="key key-flag is-critical"></i>alertă</span>
      </p>
    </section>`;
}
