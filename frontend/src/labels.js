// Romanian wording for the codes the API returns, in the words a farmer would use.
import { num, day } from './lib.js';

export const CROP = { wheat: 'Grâu', barley: 'Orz', corn: 'Porumb', sunflower: 'Floarea-soarelui', orchard: 'Livadă',
  vineyard: 'Viță-de-vie' };
export const MODE = { FROST: 'un îngheț simulat', HUMID: 'aer umed simulat', DRY: 'aer uscat simulat',
  REPLAY: 'o noapte reală de îngheț, redată accelerat' };

/**
 * What the sensor says right now: one word for the list, a headline and what to do for the sheet.
 * status is the colour: ok, warning, critical or no_data.
 */
export function verdict(sensor) {
  const s = sensor.latest;
  if (!s) {
    return { status: 'no_data', word: 'Fără date', title: 'Senzorul nu a trimis încă nimic',
      text: 'Prima măsurătoare apare aici în câteva secunde.' };
  }
  if (s.frostLevel === 'CRITICAL') {
    return { status: 'critical', word: 'Îngheț', title: 'Îngheț',
      text: 'Protejează cultura acum: pornește aspersiunea, fă fum sau acoper-o.' };
  }
  if (s.frostLevel === 'WARNING') {
    return { status: 'warning', word: 'Risc de îngheț', title: 'Se apropie înghețul',
      text: 'Urmărește temperatura și pregătește protecția: aspersiune, fum sau material de acoperit.' };
  }
  if (s.humidityLevel === 'HIGH') {
    return { status: 'warning', word: 'Aer prea umed', title: 'Aerul e prea umed',
      text: 'Aerul umed și cald aduce boli. Uită-te la frunze și pregătește tratamentul.' };
  }
  if (s.humidityLevel === 'LOW') {
    return { status: 'warning', word: 'Aer prea uscat', title: 'Aerul e prea uscat',
      text: 'Plantele pierd apă repede. Udă dacă se poate.' };
  }
  return { status: 'ok', word: 'E bine', title: 'E bine', text: 'Nu e pericol de îngheț, iar aerul e bun pentru cultură.' };
}

// What each stored alert was about, in the same words as the verdicts. Level OK (the all-clear) is not listed.
export function alertWord(alert) {
  if (alert.type === 'HUMIDITY_HIGH') return { status: 'warning', word: 'Aer prea umed' };
  if (alert.type === 'HUMIDITY_LOW') return { status: 'warning', word: 'Aer prea uscat' };
  return alert.level === 'CRITICAL' ? { status: 'critical', word: 'Îngheț' } : { status: 'warning', word: 'Risc de îngheț' };
}

// The documents a field is entered from; the same keys as DOC_TYPES in backend/app/accounts.py.
export const DOC_TYPE = {
  titlu: 'Titlu de autentificare a dreptului deținătorului de teren',
  extras: 'Extras din Registrul bunurilor imobile',
  vanzare: 'Contract de vânzare-cumpărare',
  donatie: 'Contract de donație',
  mostenire: 'Certificat de moștenitor',
  arenda: 'Contract de arendă',
  altul: 'Alt act',
};

/** "235,5 ari (2,36 ha)" */
export function areaText(ari) {
  return ari == null ? '—' : `${num(ari, 2)} ari (${num(ari / 100, 2)} ha)`;
}

/** "Titlu de autentificare ... nr. A-1234 din 12 mar. 2019" */
export function docText(field) {
  if (!field.docType) return '—';
  return `${DOC_TYPE[field.docType] || field.docType} nr. ${field.docNumber} din ${day(field.docDate)}`;
}
