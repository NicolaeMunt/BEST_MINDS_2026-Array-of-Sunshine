import { html, useState, useEffect, useRef, useMemo, api, START_PARCEL, DEMO } from './lib.js';
import { CROP, verdict } from './labels.js';
import { FieldTabs } from './FieldTabs.js';
import { SensorSheet } from './SensorSheet.js';
import { DemoMenu } from './Demo.js';
import { Account } from './Account.js';
import { AlertsPanel } from './AlertsPanel.js';

const POLL_MS = 3000;
const EMPTY = { sensors: [], alerts: [], readings: [], state: 'loading', id: null, asked: undefined };
const SEVERITY = { critical: 0, warning: 1, ok: 2, no_data: 3 };

/** All sensors plus the stored readings and the alerts of the selected one, refreshed every POLL_MS. */
function useLiveData(selected, minutes, reload) {
  const [data, setData] = useState(EMPTY);
  useEffect(() => {
    let stopped = false, timer;
    async function load() {
      try {
        const sensors = await api('/sensors/parcels');
        const id = sensors.some(s => s.id === selected) ? selected : null;
        const [alerts, readings] = !id ? [[], []] : await Promise.all([
          api('/alerts?parcelId=' + encodeURIComponent(id)).catch(() => []),
          api('/sensors/parcels/' + encodeURIComponent(id) + '/readings?minutes=' + minutes).catch(() => []),
        ]);
        if (!stopped) setData({ sensors, alerts, readings, state: 'up', id, asked: selected });
      } catch (e) {
        // 503: the API answers but the sensors service behind it does not.
        if (!stopped) setData(d => ({ ...d, state: String(e.message).includes('503') ? 'no-sensors' : 'down' }));
      }
      if (!stopped) timer = setTimeout(load, POLL_MS);
    }
    load();
    return () => { stopped = true; clearTimeout(timer); };
  }, [selected, minutes, reload]);
  return data;
}

/** The parcels with their polygons (again after the account page saves), and the satellite history of the selected one. */
function useParcels(selected, apiUp, version) {
  const [parcels, setParcels] = useState([]);
  const [history, setHistory] = useState({ id: null, data: null });
  useEffect(() => {
    if (!apiUp) return;
    api('/parcels').then(setParcels).catch(() => {});
  }, [apiUp, version]);
  useEffect(() => {
    if (!selected || !parcels.some(p => p.parcelId === selected)) return;
    let stopped = false;
    api('/parcels/' + encodeURIComponent(selected) + '/imagery/history')
      .then(data => { if (!stopped) setHistory({ id: selected, data }); })
      .catch(() => { if (!stopped) setHistory({ id: selected, data: null }); });
    return () => { stopped = true; };
  }, [selected, parcels, version]);
  return { parcels, history: history.id === selected ? history.data : null };
}

/** #/cont is the account page; anything else the fields. */
function useRoute() {
  const [route, setRoute] = useState(location.hash);
  useEffect(() => {
    const changed = () => { setRoute(location.hash); scrollTo(0, 0); };
    addEventListener('hashchange', changed);
    return () => removeEventListener('hashchange', changed);
  }, []);
  return route === '#/cont' ? 'account' : 'fields';
}

function initials(user) {
  const parts = [user.firstName, user.lastName].filter(Boolean);
  return (parts.length ? parts : [user.name || '?']).map(p => p.trim()[0] || '').join('').toUpperCase().slice(0, 2);
}

const TROUBLE = {
  loading: ['Se încarcă terenurile', ''],
  down: ['Serverul nu răspunde', 'Pornește aplicația cu start.ps1. Pagina se reîncarcă singură când serverul răspunde.'],
  'no-sensors': ['Senzorii nu răspund', 'Pornește sensors-alerts cu start.ps1. Măsurătorile apar singure când revine.'],
  up: ['Niciun teren încă', 'Terenurile apar aici imediat ce au un senzor configurat în sensors-alerts.'],
};

function App() {
  const route = useRoute();
  const [user, setUser] = useState(null);
  const [version, setVersion] = useState(0);  // bumped after the account page saves
  const [selected, setSelected] = useState(START_PARCEL);
  const [minutes, setMinutes] = useState(1440);
  const [reload, setReload] = useState(0);
  const [toast, setToast] = useState('');
  const data = useLiveData(selected, minutes, reload);
  const { parcels, history } = useParcels(selected, data.state === 'up', version);
  const parcel = parcels.find(p => p.parcelId === selected);
  useEffect(() => { api('/users/me').then(setUser).catch(() => {}); }, [version]);

  // Fields that need attention come first.
  const sensors = useMemo(() => [...data.sensors].sort((a, b) =>
    SEVERITY[verdict(a).status] - SEVERITY[verdict(b).status] || a.id.localeCompare(b.id)), [data.sensors]);
  const sensor = sensors.find(s => s.id === selected);
  const own = data.id === selected;  // the details on hand belong to the selected field

  // The server does not know the selected field (first load, or a stale ?parcel=): take the first one.
  useEffect(() => {
    if (data.state === 'up' && data.asked === selected && !sensor && sensors.length) setSelected(sensors[0].id);
  }, [data, selected, sensor, sensors]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 4000);
    return () => clearTimeout(timer);
  }, [toast]);

  // A new alert for the selected field is announced once.
  const lastAlert = useRef(null);
  useEffect(() => {
    if (!own) return;
    const newest = data.alerts.length ? data.alerts[0].timestamp : '';
    if (lastAlert.current !== null && newest > lastAlert.current) setToast(`${data.alerts[0].title}: ${data.alerts[0].parcelName}`);
    lastAlert.current = newest;
  }, [data.alerts, own]);

  function select(id) {
    lastAlert.current = null;
    setSelected(id);
    if (route !== 'fields') location.hash = '#/';
    scrollTo({ top: 0, behavior: 'smooth' });
  }

  // The logo and the name: back to the main page, on the field that needs attention most.
  function home(e) {
    e.preventDefault();
    location.hash = '#/';
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
  return html`<div className="app">
    <header className="topbar">
      <a className="brand" href="#/" onClick=${home}>
        <img src="assets/logo.png" alt="" width="44" height="44" />
        <span className="wordmark">Agronomicon</span>
      </a>
      <span className=${'conn ' + (up ? 'up' : data.state === 'loading' ? '' : 'down')}>
        ${up ? 'Se actualizează singur' : TROUBLE[data.state][0]}</span>
      ${user && html`<a className=${'user-card' + (route === 'account' ? ' is-current' : '')} href="#/cont">
        <span className="avatar" aria-hidden="true">${initials(user)}</span>
        <span className="user-text">
          <span className="user-name">${user.name}</span>
          <span className="user-mail">${user.email || 'Profilul tău'}</span>
        </span>
      </a>`}
    </header>

    ${route === 'account'
      ? html`<main className="page">
          <${Account} user=${user} parcels=${parcels} sensors=${sensors} onToast=${setToast} onSelect=${select}
                      onSaved=${() => { setVersion(n => n + 1); setReload(n => n + 1); }} />
        </main>`
      : html`
        <${FieldTabs} sensors=${sensors} selected=${selected} onSelect=${select} />
        <div className="main-grid">
          <main className="sheet">
            ${!sensor ? html`<div className="blank"><h1>${TROUBLE[data.state][0]}</h1><p>${TROUBLE[data.state][1]}</p></div>`
            : html`
              <header className="sheet-head">
                <h1>${sensor.name}</h1>
                <p className="sheet-meta">${CROP[sensor.crop] || sensor.crop || ''}${parcel && parcel.sowingDate
                  ? ` · semănat pe ${new Date(parcel.sowingDate + 'T12:00:00').toLocaleDateString('ro-RO', { day: 'numeric', month: 'long' })}` : ''}</p>
              </header>
              <${SensorSheet} key=${sensor.id} sensor=${sensor} readings=${own ? data.readings : []} minutes=${minutes}
                              onMinutes=${setMinutes} alerts=${own ? data.alerts : []} parcel=${parcel} history=${history} />`}
          </main>
          <aside className="side-panel">
            <${AlertsPanel} sensors=${sensors} onSelect=${select} reload=${reload} />
            ${DEMO && html`<${DemoMenu} sensorName=${sensor && sensor.name} onRun=${runDemo} />`}
          </aside>
        </div>`}

    <p className="toast" role="status">${toast}</p>
  </div>`;
}

ReactDOM.createRoot(document.getElementById('root')).render(html`<${App} />`);
