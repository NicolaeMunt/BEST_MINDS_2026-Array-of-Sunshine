// Presentation only (open the app with ?demo=1): each button makes the selected field's simulated sensor show a
// situation, so the alerts can be seen live; the weather outside is usually calm.
import { html } from './lib.js';

const SCENARIOS = [
  ['frost', 'Îngheț', 'Temperatura coboară în un minut sub pragul periculos al culturii.'],
  ['replay', 'O noapte reală de îngheț', 'Noaptea de 8–9 aprilie 2025, redată în trei minute.'],
  ['humid', 'Zile umede', 'Zile ploioase reale din 2026: apare riscul de boală al culturii.'],
  ['dry', 'Zile de arșiță', 'Caniculă reală din august 2026; solul rămâne uscat.'],
  ['irrigate', 'S-a udat', 'Apa din sol crește fără ploaie: aplicația vede udarea.'],
  ['normal', 'Vreme normală', 'Terenul ales revine la vremea obișnuită.'],
  ['reset', 'Resetează tot', 'Toate terenurile revin la normal, alertele se șterg.'],
];

export function DemoMenu({ sensorName, onRun }) {
  return html`<section className="demo">
    <h2>Prezentare</h2>
    <p className="note">${sensorName ? `Se aplică pe ${sensorName}.` : 'Alege întâi un teren.'}</p>
    <ul className="demo-list">
      ${SCENARIOS.map(([kind, label, what]) => html`<li key=${kind}>
        <button className="btn btn-small" onClick=${() => onRun(kind)}>${label}</button>
        <span>${what}</span>
      </li>`)}
    </ul>
  </section>`;
}
