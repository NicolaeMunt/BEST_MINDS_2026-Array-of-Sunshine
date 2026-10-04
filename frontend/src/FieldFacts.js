// What the official document says about a field: area, place, cadastral number and the document itself, and the
// outline drawn for the map and the satellite.
import { html, num } from './lib.js';
import { areaText, docText } from './labels.js';

export function FieldFacts({ field }) {
  const corners = (field.coordinates || []).length;
  return html`<dl className="facts">
    <div><dt>Suprafața</dt><dd>${areaText(field.areaAri)}</dd></div>
    <div><dt>Localitatea</dt><dd>${field.location || '—'}</dd></div>
    <div><dt>Număr cadastral</dt><dd className="mono">${field.cadastralNumber || '—'}</dd></div>
    <div className="facts-wide"><dt>Actul</dt><dd>${docText(field)}</dd></div>
    <div className="facts-wide"><dt>Pe hartă</dt><dd>${corners
      ? `contur cu ${corners} colțuri, ≈ ${num(field.outlineAri, 1)} ari; satelitul îl urmărește`
      : 'fără contur: terenul nu apare pe hartă și satelitul nu-l vede'}</dd></div>
  </dl>`;
}
