// "Ce vede satelitul": the map of the field on a chosen day, what it means in words, and the season's passes.
import { html, useState, useEffect, START_DAY } from './lib.js';
import { ParcelMap } from './ParcelMap.js';
import { pickScene, describe, hasWeakZones, isoDay, longDay, centroid } from './satellite.js';

const DAY_MS = 86400000;

/** One dot per satellite pass from April to today: filled for a clear picture, hollow for clouds. */
function SeasonLine({ history, day, onDay }) {
  const today = isoDay();
  const year = today.slice(0, 4);
  const first = [...history.results.map(r => r.sceneDate), ...history.skipped.map(s => s.sceneDate)].sort()[0] || `${year}-05-01`;
  const t0 = Date.parse(first), t1 = Date.parse(today);
  const x = d => `${(100 * (Date.parse(d) - t0) / Math.max(DAY_MS, t1 - t0)).toFixed(2)}%`;
  const months = [];
  for (let m = new Date(first + 'T12:00:00'); m <= new Date(); m.setMonth(m.getMonth() + 1, 1)) {
    if (m.getDate() === 1 || months.length === 0) months.push(isoDay(m));
  }
  const chosen = pickScene(history, day).result;
  const passes = [...history.results.map(r => ({ ...r, clear: true })), ...history.skipped.map(s => ({ ...s, clear: false }))];
  return html`<div className="season-line">
    <div className="season-track">
      ${months.map(m => html`<span key=${m} className="season-month" style=${{ left: x(m) }}>
        ${new Date(m + 'T12:00:00').toLocaleDateString('ro-RO', { month: 'short' })}</span>`)}
      <span className="season-day" style=${{ left: x(day) }} title="Ziua aleasă"></span>
      ${passes.map(p => html`<button key=${p.sceneDate + p.clear} style=${{ left: x(p.sceneDate) }}
          className=${'pass' + (p.clear ? (hasWeakZones(p) && p.affectedPct >= 5 ? ' pass-weak' : ' pass-clear') : ' pass-cloud')
            + (chosen && chosen.sceneDate === p.sceneDate && p.clear ? ' pass-chosen' : '')}
          aria-label=${`${longDay(p.sceneDate)}: ${p.clear ? 'poză bună' : 'nori'}`} title=${`${longDay(p.sceneDate)}: ${p.clear ? 'poză bună' : 'nori'}`}
          onClick=${() => onDay(p.sceneDate)}></button>`)}
    </div>
    <p className="legend">
      <span><i className="key key-pass"></i>poză bună</span>
      <span><i className="key key-pass key-pass-weak"></i>cu zone slabe</span>
      <span><i className="key key-pass key-pass-cloud"></i>nori</span>
    </p>
  </div>`;
}

export function SatelliteSection({ parcel, history }) {
  const today = isoDay();
  // ?day=2026-07-20 in the address opens that day (handy for a presentation).
  const [day, setDay] = useState(START_DAY && START_DAY <= today ? START_DAY : today);
  const scene = pickScene(history, day);
  const [showPhoto, setShowPhoto] = useState(true);
  const [showZones, setShowZones] = useState(true);
  // Weak zones are shown by default when they matter (the crop should be green), and can be turned on or off.
  useEffect(() => { setShowZones(hasWeakZones(scene.result)); }, [scene.result && scene.result.sceneDate]);

  const target = scene.result && scene.result.zoneCenter && hasWeakZones(scene.result)
    ? [scene.result.zoneCenter[1], scene.result.zoneCenter[0]] : centroid(parcel.geometry);
  return html`<section className="section">
    <h2>Ce vede satelitul</h2>
    <div className="day-pick">
      <label>Ziua: <input type="date" value=${day} max=${today} min=${`${today.slice(0, 4)}-04-01`}
        onChange=${e => e.target.value && setDay(e.target.value)} /></label>
      ${day !== today && html`<button className="btn btn-small" onClick=${() => setDay(today)}>Azi</button>`}
    </div>
    <div className="toggles" role="group" aria-label="Ce arată harta">
      <button aria-pressed=${showPhoto} onClick=${() => setShowPhoto(!showPhoto)}>Poza din satelit</button>
      <button aria-pressed=${showZones} onClick=${() => setShowZones(!showZones)}>Zonele slabe</button>
      <a className="btn btn-small go" href=${`https://www.google.com/maps/dir/?api=1&destination=${target[0]},${target[1]}`}
         target="_blank" rel="noopener">${scene.result && scene.result.zoneCenter && hasWeakZones(scene.result) ? 'Du-mă la zona slabă' : 'Du-mă la câmp'}</a>
    </div>
    <${ParcelMap} parcel=${parcel} result=${scene.result} showPhoto=${showPhoto} showZones=${showZones} />
    <div className="sat-words">${describe(scene, day === today).map((s, i) => html`<p key=${i}>${s}</p>`)}</div>
    <${SeasonLine} history=${history} day=${day} onDay=${setDay} />
    <p className="note">Sentinel-2 trece peste câmp la câteva zile; când e înnorat, rămâne poza bună de dinainte.
      Roșul arată părțile cu plante mai slabe decât restul câmpului, griul ce au ascuns norii.</p>
  </section>`;
}
