// Romanian wording for the codes the API returns, in the words a farmer would use.
import { num } from './lib.js';

export const CROP = { wheat: 'Grâu', barley: 'Orz', corn: 'Porumb', sunflower: 'Floarea-soarelui', orchard: 'Livadă',
  vineyard: 'Viță-de-vie' };
export const MODE = { FROST: 'un îngheț simulat', HUMID: 'o perioadă umedă reală din 2026, redată accelerat',
  DRY: 'o perioadă reală de aer fierbinte și uscat din 2026, redată accelerat',
  REPLAY: 'o noapte reală de îngheț, redată accelerat' };

/**
 * What the sensor says right now: one word for the list, a headline and what to do for the sheet.
 * status is the colour: ok, warning, critical or no_data.
 */
export function verdict(sensor) {
  const s = sensor.latest, w = sensor.water;
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
    return { status: 'warning', word: 'Risc de boală', title: `Risc de ${s.disease || 'boală'}`,
      text: 'Aerul a stat umed destul de mult cât să prindă boala. Uită-te la frunze și pregătește tratamentul.' };
  }
  if (s.humidityLevel === 'LOW') {
    return { status: 'warning', word: 'Arșiță', title: 'Aer fierbinte și uscat',
      text: 'Plantele pierd apă repede. Udă dacă se poate.' };
  }
  if (w && w.irrigate) {
    return { status: 'warning', word: 'De udat', title: 'E timpul să uzi',
      text: `În sol lipsesc ${num(w.deficitMm, 0)} mm de apă. Cultura iese din stres cu cel puțin ${num(w.amountMm, 0)} mm, adică ${num(w.amountMm * 10, 0)} m³ la hectar.` };
  }
  if (s.temperatureC <= 0) {
    return { status: 'ok', word: 'E bine', title: 'E sub zero, dar cultura rezistă',
      text: s.frostCriticalC == null ? `În faza „${s.phase}” înghețul nu-i face rău.`
        : `În faza „${s.phase}” cultura rezistă până la ${num(s.frostCriticalC)} °C.` };
  }
  return { status: 'ok', word: 'E bine', title: 'E bine', text: 'Nu e pericol de îngheț, iar aerul e bun pentru cultură.' };
}

/** The crop's phase and what the rules watch in it, for the line under the numbers. */
export function phaseLine(s) {
  if (!s || !s.phase) return '';
  const frost = s.frostCriticalC == null ? 'înghețul nu-i face rău acum' : `îngheț periculos de la ${num(s.frostCriticalC)} °C`;
  return `Faza: ${s.phase} · ${frost}${s.disease ? ` · urmărim riscul de ${s.disease}` : ''}.`;
}

// What each stored alert was about, in the same words as the verdicts. Level OK (the all-clear) is not listed.
export function alertWord(alert) {
  if (alert.type === 'HUMIDITY_HIGH') return { status: 'warning', word: 'Risc de boală' };
  if (alert.type === 'HUMIDITY_LOW') return { status: 'warning', word: 'Arșiță' };
  if (alert.type === 'IRRIGATION') return { status: 'warning', word: 'De udat' };
  return alert.level === 'CRITICAL' ? { status: 'critical', word: 'Îngheț' } : { status: 'warning', word: 'Risc de îngheț' };
}
