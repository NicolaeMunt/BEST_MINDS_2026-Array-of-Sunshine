// Romanian wording for the codes the API returns, in the words a farmer would use.

export const CROP = { wheat: 'Grâu', barley: 'Orz', corn: 'Porumb', sunflower: 'Floarea-soarelui', orchard: 'Livadă',
  vineyard: 'Viță-de-vie' };
export const MODE = { FROST: 'un îngheț simulat', HUMID: 'aer umed simulat', DRY: 'aer uscat simulat',
  REPLAY: 'o noapte reală de îngheț, redată accelerat' };
export const ALERT_STATUS = { high: 'critical', medium: 'warning', low: 'ok' };

/**
 * What the sensor says right now, in one word (for the list) and one sentence (for the sheet).
 * status is the colour: ok, warning, critical or no_data.
 */
export function verdict(sensor) {
  const s = sensor.latest;
  if (!s) {
    return { status: 'no_data', word: 'Fără date', title: 'Senzorul nu a trimis încă nimic',
      text: 'Prima citire apare aici în câteva secunde.' };
  }
  if (s.frostLevel === 'CRITICAL') return { status: 'critical', word: 'Îngheț', title: 'Îngheț pe parcelă', text: s.frost.message + '.' };
  if (s.frostLevel === 'WARNING') return { status: 'warning', word: 'Risc de îngheț', title: 'Se apropie înghețul', text: s.frost.message + '.' };
  if (s.humidityLevel === 'HIGH') {
    return { status: 'warning', word: 'Aer prea umed', title: 'Aerul e prea umed pentru cultură',
      text: 'Aerul umed și cald ajută bolile să apară. Uită-te la frunze și pregătește tratamentul.' };
  }
  if (s.humidityLevel === 'LOW') {
    return { status: 'warning', word: 'Aer prea uscat', title: 'Aerul e prea uscat pentru cultură',
      text: 'Plantele pierd apă mai repede decât o primesc. Udă dacă se poate.' };
  }
  return { status: 'ok', word: 'În regulă', title: 'Totul e în regulă',
    text: 'Nu e risc de îngheț, iar umiditatea aerului e bună pentru cultură.' };
}
