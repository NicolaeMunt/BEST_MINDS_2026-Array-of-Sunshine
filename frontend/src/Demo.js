// Scenarios for the presentation: they change what the simulated sensor measures.
import { html } from './lib.js';
import { Fold } from './Fold.js';

const SCENARIOS = [['frost', 'Îngheț'], ['replay', 'O noapte reală de îngheț'], ['humid', 'Aer umed și cald'],
  ['dry', 'Aer uscat și fierbinte'], ['normal', 'Vreme normală'], ['reset', 'Resetează tot']];

export function DemoMenu({ sensorName, onRun }) {
  return html`<${Fold} title="Scenarii pentru prezentare" className="demo" storageKey="demo" open=${false}>
    <p className="note">${sensorName ? `Se aplică pe ${sensorName}.` : 'Alege întâi un teren.'}</p>
    <div className="demo-buttons">
      ${SCENARIOS.map(([kind, label]) => html`<button key=${kind} className="btn btn-small" onClick=${() => onRun(kind)}>${label}</button>`)}
    </div>
  <//>`;
}
