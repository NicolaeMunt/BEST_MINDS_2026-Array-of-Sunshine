// What the official document says about a field: area, place, cadastral number and the document itself.
import { html } from './lib.js';
import { areaText, docText } from './labels.js';

export function FieldFacts({ field }) {
  return html`<dl className="facts">
    <div><dt>Suprafața</dt><dd>${areaText(field.areaAri)}</dd></div>
    <div><dt>Localitatea</dt><dd>${field.location || '—'}</dd></div>
    <div><dt>Număr cadastral</dt><dd className="mono">${field.cadastralNumber || '—'}</dd></div>
    <div className="facts-wide"><dt>Actul</dt><dd>${docText(field)}</dd></div>
  </dl>`;
}
