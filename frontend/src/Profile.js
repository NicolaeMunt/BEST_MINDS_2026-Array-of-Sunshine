// The profile: the user's details (email and phone are required), their fields and the password.
// The fields are entered by an administrator from the official documents; here they are only shown.
import { html, useState, useEffect, api, send, num, day } from './lib.js';
import { CROP, verdict } from './labels.js';
import { check, useForm, useFlash, Input, PasswordInput, FormError, Submit } from './forms.js';
import { Fold } from './Fold.js';
import { Topbar } from './Topbar.js';
import { FieldFacts } from './FieldFacts.js';

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

function FieldCard({ field, sensor }) {
  const v = sensor ? verdict(sensor) : null;
  return html`<li className="field-card">
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

  useEffect(() => {
    api('/me/fields').then(setFields).catch(e => setLoadError(e.status ? 'Terenurile nu s-au încărcat.' : 'Serverul nu răspunde.'));
    // Status and temperature for each field; the page works without them.
    api('/sensors/parcels').then(list => setSensors(Object.fromEntries(list.map(s => [s.id, s])))).catch(() => {});
  }, []);

  const totalAri = (fields || []).reduce((sum, f) => sum + (f.areaAri || 0), 0);
  return html`<div className="page">
    <${Topbar} user=${user} page="profile" onSignOut=${onSignOut} />

    <main className="profile">
      <div className="profile-head">
        <span className="avatar avatar-big" aria-hidden="true">${(user.name || '?').trim()[0].toUpperCase()}</span>
        <div>
          <h1>${user.name}</h1>
          <p className="note">${user.role === 'admin' ? 'Administrator · ' : ''}Cont creat ${day(user.createdAt)}</p>
        </div>
      </div>

      ${welcome && html`<div className="welcome">
        <h2>Bine ai venit, ${user.name.split(' ')[0]}!</h2>
        <p>Contul e gata. Terenurile tale le adaugă administratorul, după actele oficiale (titlul de autentificare
          sau extrasul din Registrul bunurilor imobile). Verifică mai jos că emailul și telefonul sunt corecte.</p>
      </div>`}

      <section className="card">
        <${Fold} title="Terenurile mele" extra=${fields ? fields.length : null} storageKey="profile-fields">
          ${loadError && html`<p className="form-error">${loadError}</p>`}
          ${fields && fields.length > 0 && html`<p className="note fields-total">
            În total ${num(totalAri, 2)} ari (${num(totalAri / 100, 2)} ha), după acte.</p>`}
          ${fields && fields.length > 0 && html`<ul className="field-cards">
            ${fields.map(f => html`<${FieldCard} key=${f.id} field=${f} sensor=${sensors[f.id]} />`)}
          </ul>`}
          <div className="info-box">
            <b>${fields && fields.length === 0 ? 'Nu ai încă terenuri înregistrate.' : 'Lipsește un teren sau e ceva greșit?'}</b>
            <p>Terenurile sunt adăugate de administrator după actele oficiale: suprafața în ari, numărul cadastral și
              actul de proprietate sau de arendă. Adu actele la administrator ca să-ți înregistreze terenul.</p>
          </div>
        <//>
      </section>

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
