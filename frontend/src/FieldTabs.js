// The fields in a row of cards, the user's own first, then the demo ones; in each group the ones that need
// attention first. One click opens a field.
import { html, num } from './lib.js';
import { CROP, verdict } from './labels.js';

function Tab({ sensor, selected, onSelect }) {
  const v = verdict(sensor);
  return html`<button className=${'field-tab is-' + v.status}
                      aria-current=${sensor.id === selected ? 'true' : undefined} onClick=${() => onSelect(sensor.id)}>
    <span className="field-tab-top">
      <span className="field-tab-name">${sensor.name}</span>
      <span className="field-tab-temp">${sensor.latest ? num(sensor.latest.temperatureC) + '°' : '—'}</span>
    </span>
    <span className="field-tab-crop">${CROP[sensor.crop] || sensor.crop}</span>
    <span className="stamp">${v.word}</span>
  </button>`;
}

export function FieldTabs({ mine, demo, signedIn, selected, onSelect }) {
  if (!mine.length && !demo.length) return null;
  // The group names only matter when there are two groups to tell apart.
  const named = signedIn;
  const group = (title, sensors, empty) => html`<div className="field-group">
    ${named && html`<h2 className="field-group-title">${title}</h2>`}
    ${sensors.length
      ? html`<div className="field-tabs-row">${sensors.map(s => html`<${Tab} key=${s.id} sensor=${s} selected=${selected} onSelect=${onSelect} />`)}</div>`
      : html`<p className="note">${empty}</p>`}
  </div>`;
  return html`<nav className="field-tabs" aria-label="Terenurile">
    ${signedIn && group('Terenurile tale', mine, 'Încă nu ai terenuri. Le adaugă administratorul, după actele oficiale.')}
    ${demo.length > 0 && group('Terenuri demonstrative', demo, '')}
  </nav>`;
}
