// The profile: the user's details (email and phone are required), their fields and the password.
// The fields are entered by an administrator from the official documents; here they are only shown.
import { html, useState, useEffect, api, send, num, day } from './lib.js';
import { CROP, verdict } from './labels.js';
import { check, useForm, useFlash, Input, PasswordInput, FormError, Submit } from './forms.js';
import { Fold } from './Fold.js';
import { Topbar } from './Topbar.js';
import { FieldFacts } from './FieldFacts.js';
import { CropSowing } from './CropSowing.js';

function Details({ user, onUser }) {
  const form = useForm({ name: user.name, email: user.email, phone: user.phone }, 'me-');
  const [flash, setFlash] = useFlash();
  async function submit(e) {
    e.preventDefault();
    const ok = await form.run({ name: v => check.name(v), email: check.email, phone: check.phone }, async v => {
      const saved = await send('PUT', '/me', v);
      onUser(saved);
      form.setValues({ name: saved.name, email: saved.email, phone: saved.phone });
    });
    if (ok) setFlash('Datele au fost salvate.');
  }
  return html`<form className="form" onSubmit=${submit} noValidate>
    <${Input} form=${form} name="name" label="Numele tău" autoComplete="name" />
    <div className="form-pair">
      <${Input} form=${form} name="email" label="Email" type="email" autoComplete="email" inputMode="email" />
      <${Input} form=${form} name="phone" label="Telefon" type="tel" autoComplete="tel" inputMode="tel" placeholder="+373 69 123 456" />
    </div>
    <p className="note">Emailul și telefonul sunt obligatorii.</p>
    <${FormError} form=${form} />
    <div className="form-actions">
      <${Submit} form=${form} busyText="Salvez…">Salvează<//>
      ${flash && html`<span className="flash" role="status">${flash}</span>`}
    </div>
  </form>`;
}

function PasswordForm() {
  const form = useForm({ current: '', new: '' }, 'pw-');
  const [flash, setFlash] = useFlash();
  async function submit(e) {
    e.preventDefault();
    const ok = await form.run({ current: v => (v ? '' : 'Scrie parola de acum.'), new: check.password },
      v => send('PUT', '/me/password', v));
    if (ok) {
      form.setValues({ current: '', new: '' });
      setFlash('Parola a fost schimbată.');
    }
  }
  return html`<form className="form" onSubmit=${submit} noValidate>
    <div className="form-pair">
      <${PasswordInput} form=${form} name="current" label="Parola de acum" autoComplete="current-password" />
      <${PasswordInput} form=${form} name="new" label="Parola nouă" autoComplete="new-password" hint="Cel puțin 8 caractere." />
    </div>
    <${FormError} form=${form} />
    <div className="form-actions">
      <${Submit} form=${form} busyText="Schimb…">Schimbă parola<//>
      ${flash && html`<span className="flash" role="status">${flash}</span>`}
    </div>
  </form>`;
}

function FieldCard({ field, sensor, onSaved }) {
  const v = sensor ? verdict(sensor) : null;
  return html`<li className=${'field-card' + (v ? ' is-' + v.status : '')}>
    <div className="field-top">
      <div className="field-text">
        <h3>${field.name}</h3>
        <p className="note">${CROP[field.crop] || field.crop} · înregistrat ${day(field.createdAt)}</p>
      </div>
      ${v && html`<div className=${'field-status is-' + v.status}>
        <span className="stamp">${v.word}</span>
        ${sensor.latest && html`<b>${num(sensor.latest.temperatureC)}°</b>`}
      </div>`}
    </div>
    <${CropSowing} field=${field} onSaved=${onSaved} />
    <${FieldFacts} field=${field} />
    <div className="field-actions">
      <a className="btn btn-small" href=${'#/?parcel=' + encodeURIComponent(field.id)}>Vezi terenul</a>
    </div>
  </li>`;
}

export function ProfilePage({ user, onUser, onSignOut, welcome }) {
  const [fields, setFields] = useState(null);  // null while loading
  const [sensors, setSensors] = useState({});
  const [loadError, setLoadError] = useState('');
  const [demo, setDemo] = useState([]);  // the demo fields, which an administrator sets up for presentations

  useEffect(() => {
    api('/me/fields').then(setFields).catch(e => setLoadError(e.status ? 'Terenurile nu s-au încărcat.' : 'Serverul nu răspunde.'));
    // Status and temperature for each field; the page works without them.
    api('/sensors/parcels').then(list => setSensors(Object.fromEntries(list.map(s => [s.id, s])))).catch(() => {});
    if (user.role === 'admin') {
      api('/parcels').then(list => setDemo(list.filter(p => p.userId !== user.id)
        .map(p => ({ id: p.parcelId, name: p.name, crop: p.crop, sowingDate: p.sowingDate })))).catch(() => {});
    }
  }, []);
  const saved = id => change => setFields(list => list.map(f => (f.id === id ? { ...f, ...change } : f)));
  const savedDemo = id => change => setDemo(list => list.map(f => (f.id === id ? { ...f, ...change } : f)));

  const totalAri = (fields || []).reduce((sum, f) => sum + (f.areaAri || 0), 0);
  // Own fields whose sensor says something is wrong: frost, disease, hot air, time to water.
  const attention = (fields || []).filter(f => sensors[f.id] && verdict(sensors[f.id]).status !== 'ok').length;
  const initials = (user.name || '?').trim().split(/\s+/).slice(0, 2).map(p => p[0]).join('').toUpperCase();
  return html`<div className="page">
    <${Topbar} user=${user} page="profile" onSignOut=${onSignOut} />

    <main className="profile">
      <header className="profile-hero">
        <span className="avatar avatar-big" aria-hidden="true">${initials}</span>
        <div className="profile-id">
          <h1>${user.name}</h1>
          <p className="profile-meta">
            ${user.role === 'admin' && html`<span className="pill">Administrator</span>`}
            <span>${user.email}</span>
            <span>Cont creat ${day(user.createdAt)}</span>
          </p>
        </div>
        <dl className="profile-stats">
          <div><dt>Terenuri</dt><dd>${fields ? fields.length : '…'}</dd></div>
          <div><dt>Suprafața</dt><dd>${fields ? num(totalAri / 100, 2) : '…'}<small> ha</small></dd></div>
          <div className=${attention ? 'is-alert' : ''}><dt>Au nevoie de atenție</dt><dd>${fields ? attention : '…'}</dd></div>
        </dl>
      </header>

      ${welcome && html`<div className="welcome">
        <h2>Bine ai venit, ${user.name.split(' ')[0]}!</h2>
        <p>Contul e gata. Terenurile tale le adaugă administratorul, după actele oficiale (titlul de autentificare
          sau extrasul din Registrul bunurilor imobile). Verifică mai jos că emailul și telefonul sunt corecte.</p>
      </div>`}

      <section className="card">
        <${Fold} title="Terenurile mele" extra=${fields ? fields.length : null} storageKey="profile-fields">
          ${loadError && html`<p className="form-error">${loadError}</p>`}
          ${!fields && !loadError && html`<ul className="field-cards" aria-label="Se încarcă terenurile">
            <li className="skeleton"></li><li className="skeleton"></li>
          </ul>`}
          ${fields && fields.length > 0 && html`<p className="note fields-total">
            În total ${num(totalAri, 2)} ari (${num(totalAri / 100, 2)} ha), după acte.</p>`}
          ${fields && fields.length > 0 && html`<ul className="field-cards">
            ${fields.map(f => html`<${FieldCard} key=${f.id} field=${f} sensor=${sensors[f.id]} onSaved=${saved(f.id)} />`)}
          </ul>`}
          <div className="info-box">
            <b>${fields && fields.length === 0 ? 'Nu ai încă terenuri înregistrate.' : 'Lipsește un teren sau e ceva greșit?'}</b>
            <p>Terenurile sunt adăugate de administrator după actele oficiale: suprafața în ari, numărul cadastral și
              actul de proprietate sau de arendă. Adu actele la administrator ca să-ți înregistreze terenul.</p>
          </div>
        <//>
      </section>

      ${user.role === 'admin' && demo.length > 0 && html`<section className="card">
        <${Fold} title="Terenuri demonstrative" extra=${demo.length} storageKey="profile-demo" open=${false}>
          <p className="note">Le văd toți vizitatorii. Ca administrator le poți schimba cultura și data semănatului
            pentru prezentare.</p>
          <ul className="field-cards">
            ${demo.map(f => html`<li key=${f.id} className="field-card">
              <div className="field-top"><div className="field-text"><h3>${f.name}</h3>
                <p className="note">nr. cadastral ${f.id}</p></div></div>
              <${CropSowing} field=${f} onSaved=${savedDemo(f.id)} />
            </li>`)}
          </ul>
        <//>
      </section>`}

      <section className="card">
        <${Fold} title="Datele tale" storageKey="profile-details">
          <${Details} user=${user} onUser=${onUser} />
        <//>
      </section>

      <section className="card">
        <${Fold} title="Parola" storageKey="profile-password" open=${false}>
          <${PasswordForm} />
        <//>
      </section>
    </main>
  </div>`;
}
