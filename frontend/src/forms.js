// Form pieces shared by the sign-in, sign-up and profile pages. The checks mirror backend/app/accounts.py,
// so most mistakes are shown before anything is sent; the server's answer is shown the same way.
import { html, useState, useEffect } from './lib.js';

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE = /^\+?\d{8,15}$/;

export const check = {
  name: (v, what = 'Numele') => !v.trim() ? `${what} lipsește.` : v.trim().length > 80 ? `${what} e prea lung.` : '',
  email: v => !v.trim() ? 'Scrie adresa de email.' : !EMAIL.test(v.trim()) ? 'Adresa de email nu arată bine. Exemplu: ion@exemplu.md' : '',
  phone: v => {
    const digits = v.replace(/[\s\-().]/g, '');
    return !digits ? 'Scrie numărul de telefon.' : !PHONE.test(digits) ? 'Numărul de telefon nu arată bine. Exemplu: +373 69 123 456' : '';
  },
  password: v => v.length < 8 ? 'Parola trebuie să aibă cel puțin 8 caractere.' : '',
};

/** Field values, their messages and a busy flag. run(rules, action): checks, then sends; returns true on success.
 * prefix keeps the element IDs apart when a page has several forms with the same field names. */
export function useForm(initial, prefix = '') {
  const [values, setValues] = useState(initial);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const set = name => value => {
    setValues(v => ({ ...v, [name]: value }));
    setErrors(e => (e[name] || e.form ? { ...e, [name]: '', form: '' } : e));
  };
  async function run(rules, action) {
    const found = {};
    for (const [name, rule] of Object.entries(rules)) {
      const message = rule(values[name] ?? '', values);
      if (message) found[name] = message;
    }
    setErrors(found);
    if (Object.keys(found).length) {
      document.getElementById('f-' + prefix + Object.keys(found)[0])?.focus();
      return false;
    }
    setBusy(true);
    try {
      await action(values);
      return true;
    } catch (e) {
      const fields = e.fields || {};
      const shown = Object.keys(fields).filter(name => name in values);
      setErrors({ ...Object.fromEntries(shown.map(name => [name, fields[name]])),
        form: shown.length ? '' : e.detail || (e.status ? 'Ceva n-a mers. Încearcă din nou.' : 'Serverul nu răspunde. Încearcă din nou.') });
      if (shown.length) document.getElementById('f-' + prefix + shown[0])?.focus();
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { values, setValues, errors, busy, set, run, prefix };
}

export function Input({ form, name, label, hint, type = 'text', ...rest }) {
  const id = 'f-' + form.prefix + name, error = form.errors[name];
  return html`<div className=${'input' + (error ? ' has-error' : '')}>
    <label htmlFor=${id}>${label}</label>
    <input id=${id} name=${name} type=${type} value=${form.values[name] ?? ''} aria-invalid=${error ? 'true' : undefined}
           aria-describedby=${error || hint ? id + '-note' : undefined} onChange=${e => form.set(name)(e.target.value)} ...${rest} />
    ${(error || hint) && html`<p id=${id + '-note'} className=${error ? 'input-error' : 'input-hint'}>${error || hint}</p>`}
  </div>`;
}

/** options: [[value, label], ...]; the first, empty choice asks the user to pick. */
export function Select({ form, name, label, options, placeholder = 'Alege…' }) {
  const id = 'f-' + form.prefix + name, error = form.errors[name];
  return html`<div className=${'input' + (error ? ' has-error' : '')}>
    <label htmlFor=${id}>${label}</label>
    <select id=${id} name=${name} value=${form.values[name] ?? ''} aria-invalid=${error ? 'true' : undefined}
            aria-describedby=${error ? id + '-note' : undefined} onChange=${e => form.set(name)(e.target.value)}>
      <option value="" disabled>${placeholder}</option>
      ${options.map(([value, text]) => html`<option key=${value} value=${value}>${text}</option>`)}
    </select>
    ${error && html`<p id=${id + '-note'} className="input-error">${error}</p>`}
  </div>`;
}

export function PasswordInput({ form, name, label, hint, autoComplete }) {
  const [shown, setShown] = useState(false);
  const id = 'f-' + form.prefix + name, error = form.errors[name];
  return html`<div className=${'input' + (error ? ' has-error' : '')}>
    <label htmlFor=${id}>${label}</label>
    <div className="input-row">
      <input id=${id} name=${name} type=${shown ? 'text' : 'password'} value=${form.values[name] ?? ''} autoComplete=${autoComplete}
             aria-invalid=${error ? 'true' : undefined} aria-describedby=${error || hint ? id + '-note' : undefined}
             onChange=${e => form.set(name)(e.target.value)} />
      <button type="button" className="input-show" aria-pressed=${shown} onClick=${() => setShown(s => !s)}>
        ${shown ? 'Ascunde' : 'Arată'}</button>
    </div>
    ${(error || hint) && html`<p id=${id + '-note'} className=${error ? 'input-error' : 'input-hint'}>${error || hint}</p>`}
  </div>`;
}

export function FormError({ form }) {
  return form.errors.form ? html`<p className="form-error" role="alert">${form.errors.form}</p>` : null;
}

export function Submit({ form, children, busyText }) {
  return html`<button type="submit" className=${'btn btn-primary' + (form.busy ? ' is-busy' : '')} disabled=${form.busy}>
    ${form.busy && html`<span className="spinner" aria-hidden="true"></span>`}${form.busy ? busyText : children}</button>`;
}

/** A short confirmation next to a button, gone after a few seconds. */
export function useFlash() {
  const [text, setText] = useState('');
  useEffect(() => {
    if (!text) return;
    const timer = setTimeout(() => setText(''), 3500);
    return () => clearTimeout(timer);
  }, [text]);
  return [text, setText];
}
