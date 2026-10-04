import { html, useState, useEffect, useRef, useMemo, api, send, hm, num, getToken, setToken, useRoute, START_PARCEL, DEMO } from './lib.js';
import { CROP, MODE, verdict } from './labels.js';
import { FieldTabs } from './FieldTabs.js';
import { SensorSheet } from './SensorSheet.js';
import { DemoMenu } from './Demo.js';
import { AlertsPanel } from './AlertsPanel.js';
import { LoginPage, RegisterPage } from './Account.js';
import { ProfilePage } from './Profile.js';
import { AdminPage } from './Admin.js';

// The page refreshes once an hour. While a scenario runs, or a new field waits for its first reading, it follows
// the sensors every few seconds; while the server is down it retries often, so the page comes back by itself.
const POLL_MS = 60 * 60 * 1000, DEMO_POLL_MS = 3000, RETRY_MS = 5000;
const EMPTY = { sensors: [], alerts: [], readings: [], state: 'loading', id: null, asked: undefined, minutes: null, updatedAt: null };
const SEVERITY = { critical: 0, warning: 1, ok: 2, no_data: 3 };

const inDemo = sensors => sensors.some(s => s.latest && MODE[s.latest.mode]);
const waiting = sensors => sensors.some(s => !s.latest);

/** All sensors plus the stored readings and the alerts of the selected one, refreshed every POLL_MS or when reload changes. */
function useLiveData(selected, minutes, reload, userId) {
  const [data, setData] = useState(EMPTY);
  useEffect(() => {
    let stopped = false, timer;
    async function load() {
      let next = RETRY_MS;
      try {
        const sensors = await api('/sensors/parcels');
        const id = sensors.some(s => s.id === selected) ? selected : null;
        const [alerts, readings] = !id ? [[], []] : await Promise.all([
          api('/alerts?parcelId=' + encodeURIComponent(id)).catch(() => []),
          api('/sensors/parcels/' + encodeURIComponent(id) + '/readings?minutes=' + minutes).catch(() => []),
        ]);
        if (!stopped) setData({ sensors, alerts, readings, state: 'up', id, asked: selected, minutes, updatedAt: new Date() });
        // A new field has no chart yet: follow it until it has two readings.
        next = inDemo(sensors) || waiting(sensors) || (id && readings.length < 2) ? DEMO_POLL_MS : POLL_MS;
      } catch (e) {
        // 503: the API answers but the sensors service behind it does not.
        if (!stopped) setData(d => ({ ...d, state: String(e.message).includes('503') ? 'no-sensors' : 'down' }));
      }
      if (!stopped) timer = setTimeout(load, next);
    }
    load();
    return () => { stopped = true; clearTimeout(timer); };
  }, [selected, minutes, reload, userId]);
  return data;
}

/** The parcels with their polygons (once), and the satellite history of the selected one (when it changes). */
function useParcels(selected, apiUp) {
  const [parcels, setParcels] = useState([]);
  const [history, setHistory] = useState({ id: null, data: null });
  useEffect(() => {
    if (!apiUp || parcels.length) return;
    // Only the parcels with a polygon go on the maps; a user's parcel gets one later, if ever.
    api('/parcels').then(list => setParcels(list.filter(p => p.geometry))).catch(() => {});
  }, [apiUp]);
  useEffect(() => {
    if (!selected || !parcels.some(p => p.parcelId === selected)) return;
    let stopped = false;
    api('/parcels/' + encodeURIComponent(selected) + '/imagery/history')
      .then(data => { if (!stopped) setHistory({ id: selected, data }); })
      .catch(() => { if (!stopped) setHistory({ id: selected, data: null }); });
    return () => { stopped = true; };
  }, [selected, parcels]);
  return { parcels, history: history.id === selected ? history.data : null };
}

const TROUBLE = {
  loading: ['Se încarcă terenurile', ''],
  down: ['Serverul nu răspunde', 'Pornește aplicația cu start.ps1. Pagina se reîncarcă singură când serverul răspunde.'],
  'no-sensors': ['Senzorii nu răspund', 'Pornește sensors-alerts cu start.ps1. Măsurătorile apar singure când revine.'],
  up: ['Niciun teren încă', 'Terenurile apar aici imediat ce au un senzor configurat în sensors-alerts.'],
};

function initials(name) {
  return (name || '?').trim().split(/\s+/).slice(0, 2).map(p => p[0] || '').join('').toUpperCase();
}

/** The right end of the top bar: sign in / sign up, or the signed-in user's card (to the profile). */
function AccountBox({ user }) {
  if (!user) {
    return html`<div className="topbar-account">
      <a className="btn btn-small btn-primary" href="#/login">Intră în cont</a>
      <a className="btn btn-small" href="#/register">Creează cont</a>
    </div>`;
  }
  return html`<div className="topbar-account">
    ${user.role === 'admin' && html`<a className="btn btn-small btn-admin" href="#/admin">Administrare</a>`}
    <a className="user-card" href="#/profile">
      <span className="avatar" aria-hidden="true">${initials(user.name)}</span>
      <span className="user-text">
        <span className="user-name">${user.name}</span>
        <span className="user-mail">${user.email || 'Profilul tău'}</span>
      </span>
    </a>
  </div>`;
}

function Dashboard({ user, startParcel }) {
  const [selected, setSelected] = useState(startParcel || START_PARCEL);
  const [minutes, setMinutes] = useState(1440);
  const [reload, setReload] = useState(0);
  const [toast, setToast] = useState('');
  const [refreshing, setRefreshing] = useState(0);  // when the refresh button was pressed, 0 when idle
  const data = useLiveData(selected, minutes, reload, user && user.id);
  const { parcels, history } = useParcels(selected, data.state === 'up');
  const parcel = parcels.find(p => p.parcelId === selected);
  const lastToast = useRef('');
  if (toast) lastToast.current = toast;  // kept on screen while the toast fades out

  // The user's own fields first, then the demo ones; in each group those that need attention come first.
  const sensors = useMemo(() => [...data.sensors].sort((a, b) => (b.own - a.own) ||
    SEVERITY[verdict(a).status] - SEVERITY[verdict(b).status] || a.id.localeCompare(b.id, undefined, { numeric: true })), [data.sensors]);
  const mine = sensors.filter(s => s.own), demo = sensors.filter(s => !s.own);
  const sensor = sensors.find(s => s.id === selected);
  // The details on hand belong to the selected sensor. Nothing selected yet is not "current": otherwise the first
  // sensor's existing alerts would be announced as new right after the page opens.
  const current = selected != null && data.id === selected;

  // The server does not know the selected sensor (first load, or a stale ?parcel=): take the first one.
  useEffect(() => {
    if (data.state === 'up' && data.asked === selected && !sensor && sensors.length) setSelected(sensors[0].id);
  }, [data, selected, sensor, sensors]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 4000);
    return () => clearTimeout(timer);
  }, [toast]);

  // A new alert for the selected sensor is announced once.
  const lastAlert = useRef(null);
  useEffect(() => {
    if (!current) return;
    const newest = data.alerts.length ? data.alerts[0].timestamp : '';
    if (lastAlert.current !== null && newest > lastAlert.current) setToast(`${data.alerts[0].title}: ${data.alerts[0].parcelName}`);
    lastAlert.current = newest;
  }, [data.alerts, current]);

  // The button spins until the answer arrives, and at least long enough to be seen.
  useEffect(() => {
    if (!refreshing) return;
    const timer = setTimeout(() => setRefreshing(0), Math.max(0, 700 - (Date.now() - refreshing)));
    return () => clearTimeout(timer);
  }, [data]);

  function refresh() {
    if (refreshing) return;
    setRefreshing(Date.now());
    setReload(n => n + 1);
  }

  function select(id) {
    lastAlert.current = null;
    setSelected(id);
    scrollTo({ top: 0, behavior: 'smooth' });
  }

  // The logo and the name: back to the top, on the field that needs attention most.
  function home(e) {
    e.preventDefault();
    if (sensors.length) select(sensors[0].id);
  }

  async function runDemo(kind) {
    if (kind !== 'reset' && !sensor) { setToast('Alege întâi un teren.'); return; }
    try {
      const result = await api(kind === 'reset' ? '/demo/reset' : `/demo/${kind}/${encodeURIComponent(sensor.id)}`, { method: 'POST' });
      setToast(result.message);
      // A replayed night needs a day on the chart, a replayed spell a week.
      if (kind !== 'reset' && kind !== 'irrigate') setMinutes({ replay: 1440, humid: 10080, dry: 10080 }[kind] || 60);
      setReload(n => n + 1);
    } catch (e) {
      // 409: nothing to replay for this crop, or a replay is running; the API says why.
      setToast(e.status === 409 && e.detail ? e.detail
        : e.status === 503 ? 'Serviciul de senzori nu răspunde.' : 'Serverul nu răspunde.');
    }
  }

  const up = data.state === 'up';
  const sown = parcel && parcel.sowingDate
    && 'semănat pe ' + new Date(parcel.sowingDate + 'T12:00:00').toLocaleDateString('ro-RO', { day: 'numeric', month: 'long' });
  return html`<div className="app">
    <header className="topbar">
      <a className="brand" href="#/" onClick=${home}>
        <img src="assets/logo-mark.png" alt="" width="44" height="44" />
        <span className="wordmark">Agronomicon</span>
      </a>
      <span className=${'conn ' + (up ? 'up' : data.state === 'loading' ? '' : 'down')}>
        ${!up ? TROUBLE[data.state][0] : inDemo(data.sensors) ? 'Demonstrație: se actualizează la câteva secunde'
          : 'Se actualizează în fiecare oră'}</span>
      <${AccountBox} user=${user} />
    </header>

    <${FieldTabs} mine=${mine} demo=${demo} signedIn=${!!user} selected=${selected} onSelect=${select} />
    <div className="main-grid">
      <main className="sheet">
        ${!sensor ? html`<div className="blank"><h1>${TROUBLE[data.state][0]}</h1><p>${TROUBLE[data.state][1]}</p></div>`
        : html`<div key=${sensor.id} className="sheet-body">
          <header className="sheet-head">
            <div>
              <h1>${sensor.name}</h1>
              <p className="sheet-meta">${[CROP[sensor.crop] || sensor.crop, sensor.areaHa != null && num(sensor.areaHa, 2) + ' ha',
                sown, !sensor.own && 'teren demonstrativ'].filter(Boolean).join(' · ')}</p>
            </div>
            <div className="refresh">
              <button className=${'btn btn-refresh' + (refreshing ? ' is-spinning' : '')} onClick=${refresh} aria-busy=${!!refreshing}>
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                  <path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v5h-5" fill="none" stroke="currentColor" strokeWidth="2.5"
                        strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Actualizează
              </button>
              ${data.updatedAt && html`<span className="note">Actualizat la ${hm(data.updatedAt)}</span>`}
            </div>
          </header>
          <${SensorSheet} sensor=${sensor} readings=${current ? data.readings : []} minutes=${minutes} onMinutes=${setMinutes}
                          alerts=${current ? data.alerts : []} drawKey=${current ? data.id + ':' + data.minutes : ''}
                          parcel=${parcel} history=${history} />
        </div>`}
      </main>
      <aside className="side-panel">
        <${AlertsPanel} sensors=${sensors} onSelect=${select} reload=${reload} />
        ${DEMO && html`<${DemoMenu} sensorName=${sensor && sensor.name} onRun=${runDemo} />`}
      </aside>
    </div>

    <p className=${'toast' + (toast ? ' is-shown' : '')} role="status">${toast || lastToast.current}</p>
  </div>`;
}

/** Who is signed in, and which page the address asks for: the fields (''), login, register, profile or admin. */
function App() {
  const { page, params, navigate } = useRoute();
  const [user, setUser] = useState(getToken() ? undefined : null);  // undefined while the stored token is checked

  useEffect(() => {
    if (user !== undefined) return;
    let timer;
    const ask = () => api('/me').then(setUser).catch(e => {
      if (e.status === 401) { setToken(''); setUser(null); }  // expired, or signed out elsewhere
      else timer = setTimeout(ask, RETRY_MS);  // server down: the token may still be good
    });
    ask();
    return () => clearTimeout(timer);
  }, [user]);

  function signedIn(session, next) {
    setToken(session.token);
    setUser(session.user);
    navigate(next);
  }
  async function signOut() {
    await send('POST', '/auth/logout').catch(() => {});
    setToken('');
    setUser(null);
    navigate('');
  }

  // Pages for signed-in users send the others to the login, and the other way round; admin is for administrators.
  const wanted = (page === 'profile' || page === 'admin') && user === null ? 'login'
    : (page === 'login' || page === 'register') && user ? 'profile'
    : page === 'admin' && user && user.role !== 'admin' ? 'profile' : null;
  useEffect(() => { if (wanted) navigate(wanted); }, [wanted]);

  if (user === undefined) return html`<div className="splash"><span className="spinner spinner-big" aria-label="Se încarcă"></span></div>`;
  if (wanted) return null;
  if (page === 'login') return html`<${LoginPage} onSignedIn=${signedIn} />`;
  if (page === 'register') return html`<${RegisterPage} onSignedIn=${signedIn} />`;
  if (page === 'admin') return html`<${AdminPage} user=${user} onSignOut=${signOut} selectedId=${params.get('user')} />`;
  if (page === 'profile') {
    return html`<${ProfilePage} key=${user.id} user=${user} onUser=${setUser} onSignOut=${signOut} welcome=${params.has('welcome')} />`;
  }
  return html`<${Dashboard} key=${(user ? user.id : 'guest') + ':' + (params.get('parcel') || '')} user=${user}
                            startParcel=${params.get('parcel')} />`;
}

ReactDOM.createRoot(document.getElementById('root')).render(html`<${App} />`);
