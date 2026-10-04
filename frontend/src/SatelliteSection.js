// "Ce vede satelitul": the map of the field on a chosen day, what it means in words, and the season's passes.
import { html, useState, useEffect, START_DAY } from './lib.js';
import { ParcelMap } from './ParcelMap.js';
import { pickScene, describe, hasWeakZones, isoDay, longDay, centroid } from './satellite.js';

const DAY_MS = 86400000;

/** "Iun" from 2026-06-01 */
function monthName(iso) {
  const s = new Date(iso + 'T12:00:00').toLocaleDateString('ro-RO', { month: 'short' }).replace('.', '');
  return s[0].toUpperCase() + s.slice(1);
}

const arrow = d => html`<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d=${d} fill="none"
  stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>`;

/** The season from the first pass's month to the end of this month: one band per month (a click picks its last good
 * picture), a lane of good pictures above a lane of cloudy passes, the chosen day, and steps between good pictures. */
function SeasonLine({ history, day, onDay }) {
  const today = isoDay();
  const dates = [...history.results.map(r => r.sceneDate), ...history.skipped.map(s => s.sceneDate)].sort();
  const firstDay = dates[0] || `${today.slice(0, 4)}-05-01`;
  const start = new Date(firstDay.slice(0, 7) + '-01T00:00:00');
  const end = new Date(today.slice(0, 7) + '-01T00:00:00');
  end.setMonth(end.getMonth() + 1);  // the whole current month, the rest of it shaded as not yet
  const span = end - start;
  const at = iso => 100 * (Date.parse(iso + 'T12:00:00') - start) / span;

  const months = [];
  for (const m = new Date(start); m < end; m.setMonth(m.getMonth() + 1)) {
    const next = new Date(m);
    next.setMonth(next.getMonth() + 1);
    const key = isoDay(m).slice(0, 7);
    months.push({ key, first: isoDay(m), share: 100 * (next - m) / span,
      clear: history.results.filter(r => r.sceneDate.startsWith(key)) });
  }
  const clear = history.results;
  const chosen = pickScene(history, day).result;
  const index = chosen ? clear.findIndex(r => r.sceneDate === chosen.sceneDate) : -1;
  const prev = index > 0 ? clear[index - 1] : null, next = index >= 0 && index < clear.length - 1 ? clear[index + 1] : null;
  const pickMonth = m => {
    const last = m.clear[m.clear.length - 1];
    if (last) return onDay(last.sceneDate);
    const lastDay = new Date(m.first + 'T12:00:00');
    lastDay.setMonth(lastDay.getMonth() + 1, 0);
    onDay(isoDay(lastDay) < today ? isoDay(lastDay) : today);
  };
  const kind = r => (hasWeakZones(r) && r.affectedPct >= 5 ? 'weak' : 'clear');

  return html`<div className="season">
    <div className="season-head">
      <button type="button" className="season-step" disabled=${!prev} onClick=${() => onDay(prev.sceneDate)}
              aria-label="Poza bună de dinainte" title="Poza bună de dinainte">${arrow('M15 6l-6 6 6 6')}</button>
      <div className="season-now" key=${chosen ? chosen.sceneDate : 'none'}>
        <b>${chosen ? longDay(chosen.sceneDate) : 'Nicio poză bună încă'}</b>
        <small>${chosen ? `poza bună ${index + 1} din ${clear.length}` : 'satelitul n-a văzut încă terenul fără nori'}</small>
      </div>
      <button type="button" className="season-step" disabled=${!next} onClick=${() => onDay(next.sceneDate)}
              aria-label="Poza bună de după" title="Poza bună de după">${arrow('M9 6l6 6-6 6')}</button>
    </div>

    <div className="season-board">
      <div className="season-months" role="group" aria-label="Alege luna">
        ${months.map(m => html`<button type="button" key=${m.key} style=${{ width: m.share + '%' }}
            className=${'season-month' + (m.key === day.slice(0, 7) ? ' is-active' : '') + (m.first > today ? ' is-future' : '')}
            disabled=${m.first > today} aria-pressed=${m.key === day.slice(0, 7)} onClick=${() => pickMonth(m)}
            title=${m.clear.length ? `${m.clear.length} poze bune` : 'nicio poză bună'}>
          <span className="season-month-name">${monthName(m.first)}</span>
          <span className="season-month-count">${m.clear.length || '–'}</span>
        </button>`)}
      </div>
      <div className="season-track">
        <span className="season-future" style=${{ left: at(today) + '%' }} aria-hidden="true"></span>
        <div className="season-lane season-lane-clear">
          ${clear.map(r => html`<button type="button" key=${r.sceneDate} style=${{ left: at(r.sceneDate) + '%' }}
              className=${'pass pass-' + kind(r) + (chosen && chosen.sceneDate === r.sceneDate ? ' pass-chosen' : '')}
              aria-label=${`${longDay(r.sceneDate)}: poză bună`} title=${`${longDay(r.sceneDate)}: poză bună`}
              onClick=${() => onDay(r.sceneDate)}></button>`)}
        </div>
        <div className="season-lane season-lane-cloud">
          ${history.skipped.map(s => html`<span key=${s.sceneDate} style=${{ left: at(s.sceneDate) + '%' }} className="pass pass-cloud"
              title=${`${longDay(s.sceneDate)}: nori`}></span>`)}
        </div>
        <span className="season-day" style=${{ left: at(day) + '%' }} title=${'Ziua aleasă: ' + longDay(day)}></span>
      </div>
    </div>

    <p className="legend season-legend">
      <span><i className="key key-pass"></i>poză bună</span>
      <span><i className="key key-pass key-pass-weak"></i>cu zone slabe</span>
      <span><i className="key key-pass key-pass-cloud"></i>nori</span>
      <span><i className="key key-day"></i>ziua aleasă</span>
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
  const fresh = !history.results.length && !history.skipped.length;  // a field just drawn: the job has not run yet

  const toZone = scene.result && scene.result.zoneCenter && hasWeakZones(scene.result);
  const target = toZone ? [scene.result.zoneCenter[1], scene.result.zoneCenter[0]] : centroid(parcel.geometry);
  return html`<section className="section sat">
    <h2>Ce vede satelitul</h2>
    <div className="sat-tools">
      <div className="toggles" role="group" aria-label="Ce arată harta">
        <button type="button" aria-pressed=${showPhoto} onClick=${() => setShowPhoto(!showPhoto)}>
          <i className="toggle-dot"></i>Poza din satelit</button>
        <button type="button" aria-pressed=${showZones} onClick=${() => setShowZones(!showZones)}>
          <i className="toggle-dot toggle-dot-weak"></i>Zonele slabe</button>
      </div>
      <label className="day-pick">
        <span>Ziua</span>
        <input type="date" value=${day} max=${today} min=${`${today.slice(0, 4)}-04-01`}
               onChange=${e => e.target.value && setDay(e.target.value)} />
      </label>
      ${day !== today && html`<button type="button" className="btn btn-small btn-today" onClick=${() => setDay(today)}>Azi</button>`}
      <a className="btn btn-small go" href=${`https://www.google.com/maps/dir/?api=1&destination=${target[0]},${target[1]}`}
         target="_blank" rel="noopener">${toZone ? 'Du-mă la zona slabă' : 'Du-mă la câmp'}</a>
    </div>
    <${ParcelMap} parcel=${parcel} result=${scene.result} showPhoto=${showPhoto} showZones=${showZones} />
    <div className="sat-words" key=${(scene.result ? scene.result.sceneDate : 'none') + day}>
      ${fresh
        ? html`<p>Terenul e nou pe hartă: satelitul îl analizează în fundal. Pozele apar aici după ce se termină
            analiza, de obicei în câteva minute.</p>`
        : describe(scene, day === today).map((s, i) => html`<p key=${i}>${s}</p>`)}
    </div>
    ${!fresh && html`<${SeasonLine} history=${history} day=${day} onDay=${setDay} />`}
    <p className="note">Sentinel-2 trece peste câmp la câteva zile; când e înnorat, rămâne poza bună de dinainte.
      Roșul arată părțile cu plante mai slabe decât restul câmpului, griul ce au ascuns norii.</p>
  </section>`;
}
