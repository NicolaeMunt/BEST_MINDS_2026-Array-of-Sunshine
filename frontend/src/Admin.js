// Administration: every account, and the fields of the chosen one, entered from the official documents
// (document, cadastral number, area in ares). Only administrators reach this page (see main.js and /admin/... in the API).
import { html, useState, useEffect, api, send, num, day } from './lib.js';
import { CROP, DOC_TYPE } from './labels.js';
import { check, useForm, useFlash, Input, Select, FormError, Submit } from './forms.js';
import { Fold } from './Fold.js';
import { Topbar } from './Topbar.js';
import { FieldFacts } from './FieldFacts.js';
import { DrawMap, outlineAri, inSatelliteArea, parseCorners, cornersText } from './DrawMap.js';

const CROPS = ['wheat', 'corn', 'sunflower', 'orchard', 'vineyard'];  // the crops of sensors-alerts
const CADASTRAL = /^\d[\d.]{3,28}\d$/;
const EMPTY = { docType: '', docNumber: '', docDate: '', cadastralNumber: '', name: '', location: '', areaAri: '', crop: '',
  coordinates: [] };

function localToday() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
}

function parseAri(text) {
  const t = String(text ?? '').trim().replace(/\s/g, '').replace(',', '.');
  return t === '' ? NaN : Number(t);
}

// In the order the form shows them, so the first mistake gets the focus. The same checks as backend/app/accounts.py.
const RULES = {
  docType: v => (v ? '' : 'Alege tipul actului.'),
  docNumber: v => (v.trim() ? '' : 'Scrie numărul actului.'),
  docDate: v => (!v ? 'Scrie data actului.' : v < '1990-01-01' || v > localToday() ? 'Data actului trebuie să fie între 1990 și azi.' : ''),
  cadastralNumber: v => {
    const c = v.replace(/\s/g, '');
    return !c ? 'Scrie numărul cadastral din act.' : !CADASTRAL.test(c) ? 'Numărul cadastral are doar cifre și puncte. Exemplu: 0100415.123' : '';
  },
  name: v => check.name(v, 'Denumirea terenului'),
  location: v => (v.trim() ? '' : 'Scrie localitatea și raionul.'),
  areaAri: v => {
    const a = parseAri(v);
    return !Number.isFinite(a) || a <= 0 || a > 10000000 ? 'Scrie suprafața din act, în ari. Exemplu: 235,5' : '';
  },
  crop: v => (v ? '' : 'Alege cultura.'),
  coordinates: v => (v.length < 3 ? 'Pune pe hartă cel puțin 3 colțuri ale terenului.' : ''),
};

/** Step 3: the outline, drawn on the map or pasted from the document; compared with the area in the document. */
function OutlineField({ form, docAri }) {
  const points = form.values.coordinates;
  const [paste, setPaste] = useState(null);  // the text box's content while it is open
  const [pasteError, setPasteError] = useState('');
  const [frame, setFrame] = useState(0);
  const error = form.errors.coordinates;
  const drawn = outlineAri(points);
  const off = Number.isFinite(docAri) && docAri > 0 && points.length >= 3 && Math.abs(drawn - docAri) / docAri > 0.15;
  function applyPaste() {
    try {
      const corners = parseCorners(paste || '');
      if (corners.length < 3) throw new Error('Sunt nevoie de cel puțin 3 colțuri, câte unul pe rând.');
      form.set('coordinates')(corners);
      setPaste(null);
      setPasteError('');
      setFrame(n => n + 1);
    } catch (e) {
      setPasteError(e.message);
    }
  }
  return html`<div className="outline">
    <${DrawMap} id=${'f-' + form.prefix + 'coordinates'} points=${points} onChange=${form.set('coordinates')} frame=${frame}
                invalid=${!!error} />
    <div className="outline-bar">
      <span className=${'outline-stat' + (points.length >= 3 ? ' is-ready' : '')}>
        ${points.length === 0 ? 'Niciun colț încă' : `${points.length} ${points.length === 1 ? 'colț' : 'colțuri'}`}
        ${points.length >= 3 && html` · contur ≈ <b>${num(drawn, 1)} ari</b>`}
      </span>
      <button type="button" className="btn btn-small" disabled=${!points.length}
              onClick=${() => form.set('coordinates')(points.slice(0, -1))}>Anulează ultimul colț</button>
      <button type="button" className="btn btn-small btn-quiet" disabled=${!points.length}
              onClick=${() => form.set('coordinates')([])}>Șterge conturul</button>
      <button type="button" className="btn btn-small btn-quiet" aria-expanded=${paste !== null}
              onClick=${() => { setPaste(paste === null ? cornersText(points) : null); setPasteError(''); }}>
        ${paste === null ? 'Lipește coordonatele' : 'Închide'}</button>
    </div>
    ${paste !== null && html`<div className="outline-paste">
      <label htmlFor=${'f-' + form.prefix + 'paste'}>Coordonatele colțurilor, câte unul pe rând: latitudine, longitudine</label>
      <textarea id=${'f-' + form.prefix + 'paste'} rows="5" value=${paste} placeholder=${'47.38121, 28.82044\n47.38190, 28.82390\n47.37950, 28.82450'}
                onChange=${e => setPaste(e.target.value)} />
      ${pasteError && html`<p className="input-error">${pasteError}</p>`}
      <button type="button" className="btn btn-small btn-primary" onClick=${applyPaste}>Pune pe hartă</button>
    </div>`}
    ${error ? html`<p className="input-error">${error}</p>`
      : off ? html`<p className="outline-warn">Conturul are ≈ ${num(drawn, 0)} ari, iar în act scrie ${num(docAri, 1)} ari.
          Verifică colțurile sau suprafața din act.</p>`
      : points.length >= 3 && !inSatelliteArea(points) ? html`<p className="outline-warn">Terenul e în afara zonei pe care o
          analizează satelitul (în jurul Orheiului): va fi pe hartă, dar fără poze din satelit.</p>`
      : html`<p className="input-hint">Satelitul analizează terenul după acest contur; terenul apare și pe harta din stânga.</p>`}
  </div>`;
}

function CropPicker({ form }) {
  const error = form.errors.crop;
  return html`<fieldset className=${'crops' + (error ? ' has-error' : '')}>
    <legend>Cultura de pe teren</legend>
    <div className="crop-chips">
      ${CROPS.map((key, i) => html`<label key=${key} className="crop-chip">
        <input type="radio" name=${form.prefix + 'crop'} value=${key} checked=${form.values.crop === key}
               id=${i === 0 ? 'f-' + form.prefix + 'crop' : undefined} onChange=${() => form.set('crop')(key)} />
        <span>${CROP[key]}</span>
      </label>`)}
    </div>
    ${error ? html`<p className="input-error">${error}</p>`
      : html`<p className="input-hint">Alertele de îngheț și umiditate folosesc pragurile acestei culturi.</p>`}
  </fieldset>`;
}

/** A field from an official document: adds one for the user, or edits `field`. */
function FieldDocForm({ userId, field, onSaved, onCancel }) {
  const form = useForm(field ? {
    docType: field.docType || '', docNumber: field.docNumber || '', docDate: field.docDate || '',
    cadastralNumber: field.cadastralNumber || '', name: field.name, location: field.location || '',
    areaAri: field.areaAri == null ? '' : String(field.areaAri).replace('.', ','), crop: field.crop,
    coordinates: field.coordinates || [],
  } : EMPTY, field ? field.id + '-' : 'new-');
  const ari = parseAri(form.values.areaAri);
  async function submit(e) {
    e.preventDefault();
    await form.run(RULES, async v => {
      const body = { ...v, areaAri: parseAri(v.areaAri) };
      const saved = await send(field ? 'PUT' : 'POST', field ? '/admin/fields/' + field.id : `/admin/users/${userId}/fields`, body);
      if (!field) form.setValues(EMPTY);
      onSaved(saved);
    });
  }
  return html`<form className="form doc-form" onSubmit=${submit} noValidate>
    <fieldset className="doc-group">
      <legend><span className="step">1</span> Actul oficial</legend>
      <${Select} form=${form} name="docType" label="Tipul actului" options=${Object.entries(DOC_TYPE)} placeholder="Alege actul…" />
      <div className="form-pair">
        <${Input} form=${form} name="docNumber" label="Numărul actului" placeholder="A-1234" />
        <${Input} form=${form} name="docDate" label="Data actului" type="date" min="1990-01-01" max=${localToday()} />
      </div>
      <${Input} form=${form} name="cadastralNumber" label="Numărul cadastral" placeholder="0100415.123" className="mono"
                disabled=${!!field} hint=${field ? 'E ID-ul terenului și nu se schimbă. Dacă e greșit, șterge terenul și adaugă-l din nou.'
                  : 'Așa cum e scris în act: cifre și puncte. Devine ID-ul terenului.'} />
    </fieldset>
    <fieldset className="doc-group">
      <legend><span className="step">2</span> Terenul</legend>
      <div className="form-pair">
        <${Input} form=${form} name="name" label="Denumirea terenului" placeholder="Livada de la deal" />
        <${Input} form=${form} name="location" label="Localitatea și raionul" placeholder="Cricova, mun. Chișinău" />
      </div>
      <${Input} form=${form} name="areaAri" label="Suprafața din act, în ari" inputMode="decimal" placeholder="235,5"
                hint=${Number.isFinite(ari) && ari > 0 ? `= ${num(ari / 100, 4)} ha` : '1 ha = 100 ari'} />
      <${CropPicker} form=${form} />
    </fieldset>
    <fieldset className="doc-group">
      <legend><span className="step">3</span> Conturul terenului</legend>
      <${OutlineField} form=${form} docAri=${ari} />
    </fieldset>
    <${FormError} form=${form} />
    <div className="form-actions">
      <${Submit} form=${form} busyText="Salvez…">${field ? 'Salvează modificările' : 'Adaugă terenul în profil'}<//>
      ${onCancel && html`<button type="button" className="btn" onClick=${onCancel}>Renunță</button>`}
    </div>
  </form>`;
}

function AdminFieldCard({ field, onChanged, onDeleted }) {
  const [mode, setMode] = useState('view');  // view | edit | delete
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function remove() {
    setBusy(true);
    try {
      await send('DELETE', '/admin/fields/' + field.id);
      onDeleted(field);
    } catch (e) {
      setError(e.status ? 'Terenul nu a putut fi șters.' : 'Serverul nu răspunde.');
      setBusy(false);
    }
  }
  if (mode === 'edit') {
    return html`<li className="field-card is-editing">
      <h3 className="edit-title">Modifici „${field.name}”</h3>
      <${FieldDocForm} field=${field} onSaved=${saved => { onChanged(saved); setMode('view'); }} onCancel=${() => setMode('view')} />
    </li>`;
  }
  return html`<li className="field-card">
    <div className="field-top">
      <div className="field-text">
        <h3>${field.name}</h3>
        <p className="note">${CROP[field.crop] || field.crop} · înregistrat ${day(field.createdAt)}</p>
      </div>
    </div>
    <${FieldFacts} field=${field} />
    ${mode === 'delete'
      ? html`<div className="confirm" role="alert">
          <p>Ștergi „${field.name}” din profilul utilizatorului, cu toate măsurătorile și alertele lui?</p>
          <div className="form-actions">
            <button className="btn btn-danger" disabled=${busy} onClick=${remove}>${busy ? 'Șterg…' : 'Da, șterge'}</button>
            <button className="btn" onClick=${() => setMode('view')}>Renunță</button>
          </div>
          ${error && html`<p className="input-error">${error}</p>`}
        </div>`
      : html`<div className="field-actions">
          <button className="btn btn-small" onClick=${() => setMode('edit')}>Modifică</button>
          <button className="btn btn-small btn-quiet" onClick=${() => setMode('delete')}>Șterge</button>
        </div>`}
  </li>`;
}

function UserDetail({ id, onChanged }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState('');
  const [flash, setFlash] = useFlash();

  useEffect(() => {
    setDetail(null);
    setError('');
    api('/admin/users/' + id).then(setDetail)
      .catch(e => setError(e.status === 404 ? 'Utilizatorul nu există.' : e.status ? 'Nu s-a încărcat.' : 'Serverul nu răspunde.'));
  }, [id]);

  if (error) return html`<div className="admin-empty"><p className="form-error">${error}</p></div>`;
  if (!detail) return html`<div className="admin-empty"><span className="spinner spinner-big" aria-label="Se încarcă"></span></div>`;

  const { user, fields } = detail;
  const totalAri = fields.reduce((sum, f) => sum + (f.areaAri || 0), 0);
  const update = list => { setDetail(d => ({ ...d, fields: list })); onChanged(); };
  function added(field) {
    update([...fields, field]);
    setFlash(`„${field.name}” a fost adăugat în profilul lui ${user.name}. Senzorul pornește în câteva secunde.`);
  }
  return html`<div className="admin-detail-body" key=${user.id}>
    <a className="admin-back" href="#/admin">← Toți utilizatorii</a>
    <div className="profile-head">
      <span className="avatar avatar-big" aria-hidden="true">${user.name.trim()[0].toUpperCase()}</span>
      <div>
        <h1>${user.name} ${user.role === 'admin' && html`<span className="badge">Administrator</span>`}</h1>
        <p className="contact">
          <a href=${'mailto:' + user.email}>${user.email}</a>
          <a href=${'tel:' + user.phone}>${user.phone}</a>
        </p>
        <p className="note">Cont creat ${day(user.createdAt)}</p>
      </div>
    </div>

    <section className="card">
      <${Fold} title="Terenuri" extra=${fields.length} storageKey="admin-fields">
        ${fields.length
          ? html`<p className="note fields-total">În total ${num(totalAri, 2)} ari (${num(totalAri / 100, 2)} ha).</p>
              <ul className="field-cards">
                ${fields.map(f => html`<${AdminFieldCard} key=${f.id} field=${f}
                  onChanged=${saved => update(fields.map(x => (x.id === saved.id ? saved : x)))}
                  onDeleted=${gone => update(fields.filter(x => x.id !== gone.id))} />`)}
              </ul>`
          : html`<p className="note">Utilizatorul nu are încă terenuri.</p>`}
      <//>
    </section>

    <section className="card">
      <${Fold} title="Adaugă teren din act" storageKey="admin-add">
        <p className="note form-lead">Copiază datele exact cum sunt în actul oficial. Terenul apare imediat în profilul
          utilizatorului și primește un senzor de aer cu pragurile culturii.</p>
        <${FieldDocForm} key=${user.id} userId=${user.id} onSaved=${added} />
        ${flash && html`<p className="flash" role="status">${flash}</p>`}
      <//>
    </section>
  </div>`;
}

export function AdminPage({ user, onSignOut, selectedId }) {
  const [users, setUsers] = useState(null);
  const [query, setQuery] = useState('');
  const [reload, setReload] = useState(0);
  const [error, setError] = useState('');

  // The list follows the search box, a moment after the typing stops.
  useEffect(() => {
    const timer = setTimeout(() => {
      api('/admin/users?q=' + encodeURIComponent(query.trim()))
        .then(list => { setUsers(list); setError(''); })
        .catch(e => setError(e.status ? 'Lista nu s-a încărcat.' : 'Serverul nu răspunde.'));
    }, users ? 250 : 0);
    return () => clearTimeout(timer);
  }, [query, reload]);

  return html`<div className="page">
    <${Topbar} user=${user} page="admin" onSignOut=${onSignOut} />
    <main className=${'admin' + (selectedId ? ' has-selection' : '')}>
      <aside className="admin-users">
        <h1>Utilizatori</h1>
        <p className="note">Alege un om ca să-i adaugi terenurile din acte.</p>
        <label className="search">
          <span className="sr-only">Caută</span>
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none"
            stroke="currentColor" strokeWidth="2.5" /><path d="M20 20l-4-4" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" /></svg>
          <input type="search" placeholder="Nume, email sau telefon" value=${query} onChange=${e => setQuery(e.target.value)} />
        </label>
        ${error && html`<p className="form-error">${error}</p>`}
        ${users && html`<p className="note users-count">${users.length} ${users.length === 1 ? 'utilizator' : 'utilizatori'}</p>`}
        ${users && users.length === 0 && html`<p className="note">Nimeni nu se potrivește căutării.</p>`}
        ${users && html`<ul className="user-list">
          ${users.map(u => html`<li key=${u.id}>
            <a className="user-row" href=${'#/admin?user=' + u.id} aria-current=${String(u.id) === selectedId ? 'true' : undefined}>
              <span className="avatar" aria-hidden="true">${u.name.trim()[0].toUpperCase()}</span>
              <span className="user-row-text">
                <b>${u.name}${u.role === 'admin' ? ' · admin' : ''}</b>
                <small>${u.email}</small>
                <small>${u.phone}</small>
              </span>
              <span className="user-row-fields">
                <b>${u.fieldCount}</b><small>${u.fieldCount === 1 ? 'teren' : 'terenuri'}</small>
                ${u.totalAri > 0 && html`<small>${num(u.totalAri / 100, 2)} ha</small>`}
              </span>
            </a>
          </li>`)}
        </ul>`}
      </aside>
      <section className="admin-detail">
        ${selectedId
          ? html`<${UserDetail} key=${selectedId} id=${selectedId} onChanged=${() => setReload(n => n + 1)} />`
          : html`<div className="admin-empty">
              <h2>Alege un utilizator</h2>
              <p className="note">În profilul lui vei vedea terenurile și vei putea adăuga altele, după actele oficiale.</p>
            </div>`}
      </section>
    </main>
  </div>`;
}
