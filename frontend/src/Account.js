// Sign-in and sign-up pages: the brand on the left, the form on the right (stacked on a phone).
import { html, send } from './lib.js';
import { check, useForm, Input, PasswordInput, FormError, Submit } from './forms.js';

function AuthShell({ title, lead, children }) {
  return html`<div className="auth">
    <aside className="auth-brand">
      <a className="auth-logo" href="#/">
        <img src="assets/logo-mark.png" alt="" width="72" height="72" />
        <span><span className="wordmark">Agronomicon</span><span className="tagline">See. Analyze. Grow.</span></span>
      </a>
      <p className="auth-pitch">Află la timp ce se întâmplă pe terenurile tale și ce ai de făcut.</p>
      <ul className="auth-points">
        <li>Alerte de îngheț, boli, arșiță și udare, după cultură și faza ei, și pe Telegram.</li>
        <li>Senzori pe fiecare teren: aerul și solul, oră cu oră.</li>
        <li>Satelitul arată ce părți ale câmpului sunt mai slabe.</li>
      </ul>
    </aside>
    <main className="auth-main">
      <div className="auth-card">
        <h1>${title}</h1>
        ${lead && html`<p className="auth-lead">${lead}</p>`}
        ${children}
      </div>
    </main>
  </div>`;
}

export function LoginPage({ onSignedIn }) {
  const form = useForm({ email: '', password: '' });
  function submit(e) {
    e.preventDefault();
    form.run({ email: check.email, password: v => (v ? '' : 'Scrie parola.') },
      async v => onSignedIn(await send('POST', '/auth/login', v), ''));
  }
  return html`<${AuthShell} title="Intră în cont" lead="Bine ai revenit. Terenurile tale te așteaptă.">
    <form className="form" onSubmit=${submit} noValidate>
      <${Input} form=${form} name="email" label="Email" type="email" autoComplete="email" inputMode="email" autoFocus />
      <${PasswordInput} form=${form} name="password" label="Parola" autoComplete="current-password" />
      <${FormError} form=${form} />
      <${Submit} form=${form} busyText="Intru…">Intră în cont<//>
    </form>
    <p className="auth-switch">Nu ai cont? <a href="#/register">Creează unul</a></p>
  <//>`;
}

export function RegisterPage({ onSignedIn }) {
  const form = useForm({ name: '', email: '', phone: '', password: '', repeat: '' });
  function submit(e) {
    e.preventDefault();
    form.run({
      name: v => check.name(v), email: check.email, phone: check.phone, password: check.password,
      repeat: (v, all) => (v !== all.password ? 'Parolele nu sunt la fel.' : ''),
    }, async ({ repeat, ...v }) => onSignedIn(await send('POST', '/auth/register', v), 'profile?welcome=1'));
  }
  return html`<${AuthShell} title="Creează cont" lead="Durează un minut. Terenurile ți le adaugă apoi administratorul, după acte.">
    <form className="form" onSubmit=${submit} noValidate>
      <${Input} form=${form} name="name" label="Numele tău" autoComplete="name" placeholder="Ion Popescu" autoFocus />
      <${Input} form=${form} name="email" label="Email" type="email" autoComplete="email" inputMode="email" placeholder="ion@exemplu.md" />
      <${Input} form=${form} name="phone" label="Telefon" type="tel" autoComplete="tel" inputMode="tel" placeholder="+373 69 123 456" />
      <${PasswordInput} form=${form} name="password" label="Parola" autoComplete="new-password" hint="Cel puțin 8 caractere." />
      <${PasswordInput} form=${form} name="repeat" label="Repetă parola" autoComplete="new-password" />
      <${FormError} form=${form} />
      <${Submit} form=${form} busyText="Creez contul…">Creează contul<//>
    </form>
    <p className="auth-switch">Ai deja cont? <a href="#/login">Intră în cont</a></p>
  <//>`;
}
