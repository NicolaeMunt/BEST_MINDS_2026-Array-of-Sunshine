// What grows on a field and when it was sown: the farmer sets them, and the alerts follow at once.
import { html, useState, useEffect, send, api } from './lib.js';
import { CROP } from './labels.js';

let cropList = null;  // GET /crops, asked once per page load

function useCrops() {
  const [crops, setCrops] = useState(cropList || []);
  useEffect(() => {
    if (cropList) return;
    api('/crops').then(list => { cropList = list; setCrops(list); }).catch(() => {});
  }, []);
  return crops;
}

/** field: { id, crop, sowingDate }. onSaved({ crop, sowingDate }) after a save. */
export function CropSowing({ field, onSaved }) {
  const crops = useCrops();
  const [crop, setCrop] = useState(field.crop || '');
  const [sowing, setSowing] = useState(field.sowingDate || '');
  const [status, setStatus] = useState('');  // '', 'saving', or what to tell the farmer
  const sown = key => !!(crops.find(c => c.key === key) || {}).sown;
  const date = sown(crop) ? sowing || null : null;
  const changed = crop !== (field.crop || '') || date !== (field.sowingDate || null);

  async function save(e) {
    e.preventDefault();
    setStatus('saving');
    const path = '/parcels/' + encodeURIComponent(field.id);
    try {
      if (crop !== field.crop) await send('PUT', path + '/crop', { crop });
      if (date !== (field.sowingDate || null)) await send('PUT', path + '/sowing', { sowingDate: date });
      setStatus('Salvat. Alertele urmează de acum cultura și data semănatului.');
      onSaved({ crop, sowingDate: date });
    } catch (err) {
      setStatus(err.detail || 'Nu am putut salva. Încearcă din nou.');
    }
  }

  return html`<form className="crop-sowing" onSubmit=${save}>
    <label className="field">
      <span>Cultura</span>
      <select value=${crop} onChange=${e => { setCrop(e.target.value); setStatus(''); }}>
        ${!crops.some(c => c.key === crop) && html`<option value=${crop}>${CROP[crop] || crop || '—'}</option>`}
        ${crops.map(c => html`<option key=${c.key} value=${c.key}>${CROP[c.key] || c.name}</option>`)}
      </select>
    </label>
    <label className="field">
      <span>Semănat pe</span>
      ${sown(crop)
        ? html`<input type="date" value=${sowing} onInput=${e => { setSowing(e.target.value); setStatus(''); }} />`
        : html`<span className="field-none">nu se seamănă în fiecare an</span>`}
    </label>
    <button type="submit" className="btn btn-small btn-primary" disabled=${!changed || status === 'saving'}>
      ${status === 'saving' ? 'Salvez…' : 'Salvează'}</button>
    ${status && status !== 'saving' && html`<p className="note crop-sowing-status" role="status">${status}</p>`}
  </form>`;
}
