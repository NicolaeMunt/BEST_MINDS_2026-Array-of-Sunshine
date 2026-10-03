import { html, num } from './lib.js';
import { CROP, verdict } from './labels.js';

export function SensorList({ sensors, selected, onSelect }) {
  if (!sensors.length) return html`<p className="sensors-empty">Niciun teren de arătat.</p>`;
  return html`<ul className="sensor-list">
    ${sensors.map(sensor => {
      const v = verdict(sensor);
      return html`<li key=${sensor.id}>
        <button className=${'sensor is-' + v.status} aria-current=${sensor.id === selected ? 'true' : undefined}
                onClick=${() => onSelect(sensor.id)}>
          <span className="sensor-text">
            <span className="sensor-name">${sensor.name}</span>
            <span className="sensor-crop">${CROP[sensor.crop] || sensor.crop}</span>
            <span className="stamp">${v.word}</span>
          </span>
          <span className="sensor-temp">${sensor.latest ? num(sensor.latest.temperatureC) + '°' : '—'}</span>
        </button>
      </li>`;
    })}
  </ul>`;
}
