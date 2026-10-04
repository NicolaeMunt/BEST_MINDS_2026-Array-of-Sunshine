// What the satellite saw on a chosen day, in the words a farmer would use. No NDVI, no codes.
import { num } from './lib.js';

const DIRECTION = { N: 'nord', NE: 'nord-est', E: 'est', SE: 'sud-est', S: 'sud', SW: 'sud-vest', W: 'vest',
  NW: 'nord-vest' };
const DAY_MS = 86400000;

/** YYYY-MM-DD of a local date. */
export function isoDay(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

/** "28 iunie" */
export function longDay(iso) {
  return new Date(iso + 'T12:00:00').toLocaleDateString('ro-RO', { day: 'numeric', month: 'long' });
}

/** The newest picture taken on `day` or before, how old it is, and the cloudy passes since. */
export function pickScene(history, day) {
  const results = history ? history.results.filter(r => r.sceneDate <= day) : [];
  const result = results.length ? results[results.length - 1] : null;
  const skipped = history ? history.skipped.filter(s => s.sceneDate <= day && (!result || s.sceneDate > result.sceneDate)) : [];
  const daysOld = result ? Math.round((Date.parse(day) - Date.parse(result.sceneDate)) / DAY_MS) : null;
  return { result, skipped, daysOld };
}

/** Weak zones worth a look: the crop should be green and part of the field is not. */
export function hasWeakZones(result) {
  return !!result && result.affectedPct > 0 && (!result.season || result.season === 'growing');
}

function ago(daysOld, today) {
  if (daysOld === 0) return today ? 'azi' : 'chiar în ziua aleasă';
  if (daysOld === 1) return today ? 'ieri' : 'cu o zi înainte';
  return today ? `acum ${daysOld} zile` : `cu ${daysOld} zile înainte`;
}

function dateList(items) {
  const days = items.map(s => longDay(s.sceneDate));
  return days.length <= 3 ? days.join(', ') : `${days.slice(0, 3).join(', ')} și încă ${days.length - 3} zile`;
}

/** Sentences about the scene for the chosen day; `today` says whether that day is today. */
export function describe({ result, skipped, daysOld }, today) {
  if (!result) return ['Încă nu e nicio poză fără nori până în această zi.'];
  const out = [`Poza din ${longDay(result.sceneDate)} (${ago(daysOld, today)})${result.phase ? `, faza „${result.phase}”` : ''}.`];
  if (skipped.length) out.push(`De atunci au fost nori (${dateList(skipped)}).`);

  switch (result.season) {
    case 'dormant':
      out.push('Câmp în repaus sau nesemănat: e normal să se vadă pământ.');
      break;
    case 'establishing':
      out.push('Plantele sunt mici: e normal să se vadă pământ.');
      break;
    case 'maturing':
      out.push('Cultura se coace: e normal să se îngălbenească.');
      break;
    case 'harvested':
      out.push('Câmpul e recoltat.');
      break;
    default:
      if (result.affectedPct === 0) {
        out.push('Tot câmpul arată bine.');
      } else {
        const where = result.affectedSector === 'scattered' ? 'în mai multe locuri'
          : result.affectedSector === 'C' ? 'în mijloc' : `spre ${DIRECTION[result.affectedSector] || 'o margine'}`;
        out.push(`${num(result.affectedPct, 1)}% din câmp e mai slab, ${where}.`);
        if (result.zoneConfirmed === true) out.push('Se vedea și în poza dinainte: merită verificat.');
        if (result.zoneConfirmed === false) out.push('Pată nouă: poate fi și o umbră.');
      }
  }

  const codes = new Set(result.warnings.map(w => w.code));
  if (codes.has('possible_cloud')) out.push('E lângă un nor: poate fi umbra lui.');
  if (codes.has('low_vegetation')) out.push('Câmpul e mai puțin verde decât ar trebui acum.');
  if (codes.has('whole_field_drop')) out.push('Tot câmpul a pălit: grindină, secetă sau boală?');
  if (codes.has('low_pixel_count')) out.push('Câmp mic pentru satelit: cifre aproximative.');
  return out;
}

/** Centre of a GeoJSON polygon, [lat, lon]. */
export function centroid(geometry) {
  const ring = geometry.coordinates[0];
  return [ring.reduce((s, p) => s + p[1], 0) / ring.length, ring.reduce((s, p) => s + p[0], 0) / ring.length];
}

/** Polygon ring as Leaflet [lat, lon] pairs. */
export function latLngs(geometry) {
  return geometry.coordinates[0].map(([lon, lat]) => [lat, lon]);
}
