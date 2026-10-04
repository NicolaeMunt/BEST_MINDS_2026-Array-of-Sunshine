// The farmer's profile: name and e-mail, then the fields: where they are, what grows on each and when it was sown.
import { html, useState, useEffect, api } from './lib.js';
import { CROP, verdict } from './labels.js';
import { OverviewMap } from './OverviewMap.js';

export function Account({ user, parcels, sensors, onSaved, onToast, onSelect }) {
  const [crops, setCrops] = useState([]);
  const [form, setForm] = useState({ firstName: '', lastName: '', email: '' });
  const [fields, setFields] = useState({});  // parcel ID -> {crop, sowingDate}
  const [saving, setSaving] = useState(false);

  useEffect(() => { api('/crops').then(setCrops).catch(() => {}); }, []);
  useEffect(() => {
    if (user) setForm({ firstName: user.firstName || '', lastName: user.lastName || '', email: user.email || '' });
  }, [user]);
  useEffect(() => {
    setFields(Object.fromEntries(parcels.map(p => [p.parcelId, { crop: p.crop, sowingDate: p.sowingDate || '' }])));
  }, [parcels]);

  const sown = key => (crops.find(c => c.key === key) || {}).sown;
  const set = (id, change) => setFields({ ...fields, [id]: { ...fields[id], ...change } });
  const input = (key, label, type = 'text', hint = '') => html`<label className="field">
    <span>${label}</span>
    <input type=${type} value=${form[key]} autoComplete=${{ firstName: 'given-name', lastName: 'family-name', email: 'email' }[key]}
           placeholder=${hint} onInput=${e => setForm({ ...form, [key]: e.target.value })} />
  </label>`;

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    const put = (path, body) => api(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    try {
      await put('/users/me', form);
      for (const p of parcels) {
        const f = fields[p.parcelId];
        if (!f) continue;
        if (f.crop && f.crop !== p.crop) await put(`/parcels/${encodeURIComponent(p.parcelId)}/crop`, { crop: f.crop });
        const date = sown(f.crop) ? f.sowingDate || null : null;
        if (date !== (p.sowingDate || null)) await put(`/parcels/${encodeURIComponent(p.parcelId)}/sowing`, { sowingDate: date });
      }
      onToast('Am salvat.');
      onSaved();
    } catch (err) {
      onToast(err.status === 422 && err.detail ? String(err.detail) : 'Nu am putut salva. Încearcă din nou.');
    }
    setSaving(false);
  }

  return html`<form className="account" onSubmit=${save}>
    <header className="sheet-head"><h1>Contul tău</h1></header>

    <section className="section">
      <h2>Datele tale</h2>
      <div className="fields">
        ${input('firstName', 'Prenume')}
        ${input('lastName', 'Nume')}
        ${input('email', 'E-mail', 'email', 'nume@gmail.com')}
      </div>
    </section>

    <section className="section">
      <h2>Terenurile tale</h2>
      <p className="note">Alertele de îngheț, boli și udare urmează cultura și data semănatului, imediat.
        La porumb și floarea-soarelui, toate fazele se mută după ziua în care ai semănat.</p>
      ${parcels.length > 0 && html`<${OverviewMap} parcels=${parcels} sensors=${sensors} onSelect=${onSelect} />`}
      <ul className="parcel-rows">
        ${parcels.map(p => {
          const f = fields[p.parcelId] || {};
          const sensor = sensors.find(s => s.id === p.parcelId);
          const v = sensor ? verdict(sensor) : null;
          return html`<li key=${p.parcelId} className=${v ? 'is-' + v.status : ''}>
            <span className="parcel-row-name">
              <b>${p.name}</b>
              <small>nr. cadastral ${p.parcelId}${p.idsFictive ? ' (fictiv)' : ''}</small>
              ${v && html`<span className="stamp">${v.word}</span>`}
            </span>
            <label className="field">
              <span>Cultura</span>
              <select value=${f.crop || ''} onChange=${e => set(p.parcelId, { crop: e.target.value })}>
                ${crops.map(c => html`<option key=${c.key} value=${c.key}>${CROP[c.key] || c.name}</option>`)}
              </select>
            </label>
            <label className="field">
              <span>Semănat pe</span>
              ${sown(f.crop)
                ? html`<input type="date" value=${f.sowingDate || ''} onInput=${e => set(p.parcelId, { sowingDate: e.target.value })} />`
                : html`<span className="field-none">nu se seamănă în fiecare an</span>`}
            </label>
          </li>`;
        })}
      </ul>
    </section>

    <div className="account-actions">
      <button type="submit" className="btn btn-primary" disabled=${saving}>${saving ? 'Se salvează…' : 'Salvează'}</button>
      <a className="btn" href="#/">Înapoi la terenuri</a>
    </div>
  </form>`;
}
