// One field: what the sensor means right now, the two numbers, the soil water, the temperature over time and the alerts.
import { html, useState, num, hm, when, day } from './lib.js';
import { MODE, verdict, alertWord, phaseLine } from './labels.js';
import { SatelliteSection } from './SatelliteSection.js';

// Minutes since 1 April of this year: the whole season on one chart.
const SEASON = Math.ceil((Date.now() - new Date(new Date().getFullYear(), 3, 1)) / 60000);
// [minutes, button label, how the alert list names the period]
const RANGES = [[15, 'Acum', 'din ultimele 15 minute'], [1440, 'O zi', 'din ultima zi'],
  [10080, 'O săptămână', 'din ultima săptămână'], [SEASON, 'Din aprilie', 'din aprilie până azi']];
const SHOWN_ALERTS = 5;
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

/** Whether the crop needs water: from the soil probe when it reports, else from the temperature and rain (FAO-56). */
function WaterSection({ water: w }) {
  const sensor = w.source === 'sensor';
  return html`<section className="section">
    <h2>Apa din sol</h2>
    ${!w.hasCrop ? html`<p>În faza „${w.phase}” nu e nimic de udat.</p>` : html`
      <div className="figures">
        ${sensor
          ? html`<div className="figure"><b>${num(w.soilMoisturePct, 0)}<small>%</small></b><span>apă în sol acum</span></div>
            <div className="figure"><b>${num(w.thresholdPct, 0)}<small>%</small></b><span>sub atât suferă cultura</span></div>`
          : html`<div className="figure"><b>${num(w.deficitMm, 0)}<small>mm</small></b><span>lipsesc din sol</span></div>
            <div className="figure"><b>${num(w.readilyAvailableMm, 0)}<small>mm</small></b><span>de la cât lipsă suferă cultura</span></div>`}
      </div>
      <p>${w.irrigate ? `E timpul să uzi. Cultura iese din stres cu cel puțin ${num(w.amountMm, 0)} mm, adică ${num(w.amountMm * 10, 0)} m³ la hectar.`
        : sensor ? `Cultura are apă destulă. Udă când solul coboară sub ${num(w.thresholdPct, 0)}%.`
        : `Cultura mai are apă: udă când lipsesc peste ${num(w.readilyAvailableMm, 0)} mm.`}</p>`}
    ${w.waterings && w.waterings.length > 0 && html`<p>Am văzut că ai udat: ${w.waterings.map(x =>
      `${when(x.time)} (de la ${num(x.fromPct, 0)}% la ${num(x.toPct, 0)}%)`).join(', ')}.</p>`}
    <p className="note">${sensor ? 'Măsurat de senzorul de sol la 20 cm. Când uzi, senzorul vede apa și sfatul se schimbă singur.'
      : 'Socotit din temperatura și ploaia măsurate din 1 mai, după metoda FAO; fără senzor de sol nu știm dacă ai udat.'}</p>
  </section>`;
}

export function SensorSheet({ sensor, readings, minutes, onMinutes, alerts, parcel, history }) {
  const s = sensor.latest, v = verdict(sensor), drop = s && s.dropLastHourC;
  const trend = drop == null ? '' : drop > 0.3 ? `Se răcește: cu ${num(drop)}° mai rece decât acum o oră.`
    : drop < -0.3 ? `Se încălzește: cu ${num(-drop)}° mai cald decât acum o oră.` : 'Temperatura stă pe loc față de acum o oră.';
  const range = RANGES.find(r => r[0] === minutes) || RANGES[1];
  const sent = alerts.filter(a => a.level !== 'OK');  // the "danger has passed" messages are left out
  // The list follows the chart's period. It counts back from now, so alerts show during a replayed night too.
  const inPeriod = sent.filter(a => Date.parse(a.timestamp) >= Date.now() - minutes * 60000);
  const [showAll, setShowAll] = useState(false);
  const listed = showAll ? inPeriod : inPeriod.slice(0, SHOWN_ALERTS);
  const banded = minutes > 1440;
  return html`
    <section className=${'verdict is-' + v.status}>
      <h2>${v.title}</h2>
      <p>${v.text}</p>
    </section>
    ${s && MODE[s.mode] && html`<p className="note demo-note">Demonstrație: senzorul arată ${MODE[s.mode]}, nu vremea de afară.</p>`}

    ${s && html`<section className="section">
      <h2>Acum</h2>
      <div className="figures">
        <div className="figure"><b>${num(s.temperatureC)}<small>°C</small></b><span>temperatura aerului</span></div>
        <div className="figure"><b>${num(s.humidityPct, 0)}<small>%</small></b><span>umiditatea aerului</span></div>
        ${s.soilTemperatureC != null && html`<div className="figure"><b>${num(s.soilTemperatureC)}<small>°C</small></b><span>solul la 5 cm</span></div>`}
        ${s.soilMoisturePct != null && html`<div className="figure"><b>${num(s.soilMoisturePct, 0)}<small>%</small></b><span>apă în sol la 20 cm</span></div>`}
      </div>
      <p>${trend}</p>
      ${phaseLine(s) && html`<p>${phaseLine(s)}</p>`}
      <p className="note">Măsurat ${when(s.timestamp)}.</p>
    </section>`}

    ${parcel && history && html`<${SatelliteSection} parcel=${parcel} history=${history} />`}

    ${sensor.water && html`<${WaterSection} water=${sensor.water} />`}

    <section className="section">
      <h2>Temperatura</h2>
      <div className="ranges" role="group" aria-label="Ce perioadă arată graficul">
        ${RANGES.map(([value, label]) => html`<button key=${value} aria-pressed=${minutes === value}
          onClick=${() => { setShowAll(false); onMinutes(value); }}>${label}</button>`)}
      </div>
      <${TempChart} readings=${readings} minutes=${minutes} alerts=${sent} />
      <p className="legend">
        ${banded && html`<span><i className="key key-band"></i>de la cea mai rece la cea mai caldă oră ${minutes > 20160 ? 'a zilei' : ''}</span>`}
        <span><i className="key key-zero"></i>sub zero: îngheț</span>
        <span><i className="key key-flag is-warning"></i><i className="key key-flag is-critical"></i>alertă</span>
      </p>
    </section>

    <section className="section">
      <h2>Alerte ${range[2]}</h2>
      ${inPeriod.length === 0
        ? html`<p className="note">Nicio alertă în această perioadă. Alertele ajung și pe Telegram.</p>`
        : html`<ul className="alerts">
          ${listed.map(a => html`<li key=${a.timestamp + a.type + a.level} className=${'is-' + alertWord(a).status}>
            <span className="stamp">${alertWord(a).word}</span>
            <span className="alert-facts">${a.type === 'IRRIGATION' ? `lipsesc ${num(a.deficitMm, 0)} mm de apă în sol`
              : a.type === 'SOWING' ? `solul are ${num(a.temperatureC)}°C la 5 cm`
              : `${num(a.temperatureC)}°C, umiditate ${num(a.humidityPct, 0)}%`}</span>
            <time>${day(a.timestamp, false)}, ${hm(new Date(a.timestamp))}</time>
          </li>`)}
        </ul>`}
      ${inPeriod.length > listed.length && html`<button className="btn more" onClick=${() => setShowAll(true)}>
        Arată toate cele ${inPeriod.length}</button>`}
    </section>`;
}
