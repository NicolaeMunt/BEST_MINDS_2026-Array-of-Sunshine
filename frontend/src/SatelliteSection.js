// "Ce vede satelitul": the map of the field on a chosen day, the weak zones in red over it, and what it means in words.
import { html, useState, useEffect, START_DAY } from './lib.js';
import { ParcelMap } from './ParcelMap.js';
import { pickScene, describe, hasWeakZones, isoDay, centroid } from './satellite.js';

const SHOWN_SENTENCES = 2;  // the rest waits under "Mai mult"
export function SatelliteSection({ parcel, history }) {
  const today = isoDay();
  // ?day=2026-07-20 in the address opens that day (handy for a presentation).
  const [day, setDay] = useState(START_DAY && START_DAY <= today ? START_DAY : today);
  const [showZones, setShowZones] = useState(true);
  const scene = pickScene(history, day);
  const words = describe(scene, day === today);
  // Weak zones are shown when they matter (the crop should be green); one button hides them.
  useEffect(() => { setShowZones(true); }, [scene.result && scene.result.sceneDate]);
  const fresh = !history.results.length && !history.skipped.length;  // a field just drawn: the job has not run yet
  const weak = hasWeakZones(scene.result);
  // The clear pictures just before and just after the one shown.
  const shown = scene.result ? history.results.findIndex(r => r.sceneDate === scene.result.sceneDate) : -1;
  const before = shown > 0 ? history.results[shown - 1] : null;
  const after = history.results[shown + 1] || null;
  const target = weak && scene.result.zoneCenter ? [scene.result.zoneCenter[1], scene.result.zoneCenter[0]] : centroid(parcel.geometry);

  return html`<section className="section sat">
    <h2>Ce vede satelitul</h2>
    <div className="sat-bar">
      <span className="day-step">
        <button className="btn btn-small day-arrow" disabled=${!before} aria-label="Poza dinainte" title="Poza dinainte"
                onClick=${() => before && setDay(before.sceneDate)}>‹</button>
        <input type="date" aria-label="Ziua" value=${day} max=${today} min=${`${today.slice(0, 4)}-04-01`}
               onChange=${e => e.target.value && setDay(e.target.value)} />
        <button className="btn btn-small day-arrow" disabled=${!after} aria-label="Poza următoare" title="Poza următoare"
                onClick=${() => after && setDay(after.sceneDate)}>›</button>
      </span>
      ${day !== today && html`<button className="btn btn-small" onClick=${() => setDay(today)}>Azi</button>`}
      <span className="sat-bar-end">
        ${weak && html`<button className="btn btn-small" aria-pressed=${!showZones} onClick=${() => setShowZones(!showZones)}>
          ${showZones ? 'Ascunde zonele' : 'Arată zonele'}</button>`}
        <a className="btn btn-small go" href=${`https://www.google.com/maps/dir/?api=1&destination=${target[0]},${target[1]}`}
           target="_blank" rel="noopener">${weak ? 'Du-mă la zona slabă' : 'Du-mă la câmp'}</a>
      </span>
    </div>
    <${ParcelMap} parcel=${parcel} result=${scene.result} showPhoto=${true} showZones=${showZones} />
    <div className="sat-words" key=${(scene.result ? scene.result.sceneDate : 'none') + day}>
      ${fresh
        ? html`<p>Terenul e nou pe hartă: satelitul îl analizează în fundal. Pozele apar aici în câteva minute.</p>`
        : html`${words.slice(0, SHOWN_SENTENCES).map((s, i) => html`<p key=${i}>${s}</p>`)}
          ${words.length > SHOWN_SENTENCES && html`<details className="more-words"><summary>Mai mult</summary>
            ${words.slice(SHOWN_SENTENCES).map((s, i) => html`<p key=${i}>${s}</p>`)}</details>`}`}
    </div>
    ${weak && html`<p className="note">Roșu: plante mai slabe decât restul câmpului.</p>`}
  </section>`;
}
