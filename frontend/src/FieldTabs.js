// The fields in a row of cards, the ones that need attention first: one click opens a field.
import { html, num } from './lib.js';
import { CROP, verdict } from './labels.js';

export function FieldTabs({ sensors, selected, onSelect }) {
  if (!sensors.length) return null;
  return html`<nav className="field-tabs" aria-label="Terenurile tale">
    ${sensors.map(sensor => {
      const v = verdict(sensor);
      return html`<button key=${sensor.id} className=${'field-tab is-' + v.status}
                          aria-current=${sensor.id === selected ? 'true' : undefined} onClick=${() => onSelect(sensor.id)}>
        <span className="field-tab-top">
          <span className="field-tab-name">${sensor.name}</span>
          <span className="field-tab-temp">${sensor.latest ? num(sensor.latest.temperatureC) + '°' : '—'}</span>
        </span>
        <span className="field-tab-crop">${CROP[sensor.crop] || sensor.crop}</span>
        <span className="stamp">${v.word}</span>
      </button>`;
    })}
  </nav>`;
}
