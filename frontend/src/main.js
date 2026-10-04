import { html, useState, useEffect, useRef, useMemo, api, START_PARCEL } from './lib.js';
import { CROP, verdict } from './labels.js';
import { SensorList } from './SensorList.js';
import { SensorSheet } from './SensorSheet.js';
import { DemoMenu } from './Demo.js';

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

const TROUBLE = {
  loading: ['Se încarcă terenurile', ''],
  down: ['Serverul nu răspunde', 'Pornește aplicația cu start.ps1. Pagina se reîncarcă singură când serverul răspunde.'],
  'no-sensors': ['Senzorii nu răspund', 'Pornește sensors-alerts cu start.ps1. Măsurătorile apar singure când revine.'],
  up: ['Niciun teren încă', 'Terenurile apar aici imediat ce au un senzor configurat în sensors-alerts.'],
};

function App() {
  const [selected, setSelected] = useState(START_PARCEL);
  const [minutes, setMinutes] = useState(1440);
  const [reload, setReload] = useState(0);
  const [toast, setToast] = useState('');
  const data = useLiveData(selected, minutes, reload);

  // Sensors that need attention come first.
  const sensors = useMemo(() => [...data.sensors].sort((a, b) =>
    SEVERITY[verdict(a).status] - SEVERITY[verdict(b).status] || a.id.localeCompare(b.id)), [data.sensors]);
  const sensor = sensors.find(s => s.id === selected);
  const own = data.id === selected;  // the details on hand belong to the selected sensor

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
    if (!own) return;
    const newest = data.alerts.length ? data.alerts[0].timestamp : '';
    if (lastAlert.current !== null && newest > lastAlert.current) setToast(`${data.alerts[0].title}: ${data.alerts[0].parcelName}`);
    lastAlert.current = newest;
  }, [data.alerts, own]);

  function select(id) {
    lastAlert.current = null;
    setSelected(id);
  }

  async function runDemo(kind) {
    if (kind !== 'reset' && !sensor) { setToast('Alege întâi un teren.'); return; }
    try {
      const result = await api(kind === 'reset' ? '/demo/reset' : `/demo/${kind}/${encodeURIComponent(sensor.id)}`, { method: 'POST' });
      setToast(result.message);
      // A replayed night needs a day on the chart, a replayed spell a week.
      if (kind !== 'reset') setMinutes({ replay: 1440, humid: 10080, dry: 10080 }[kind] || 15);
      setReload(n => n + 1);
    } catch (e) {
      // 409: nothing to replay for this crop; the API says why.
      setToast(e.status === 409 && e.detail ? e.detail
        : e.status === 503 ? 'Serviciul de senzori nu răspunde.' : 'Serverul nu răspunde.');
    }
  }

  const up = data.state === 'up';
  return html`<div className="shell">
    <aside className="side">
      <p className="wordmark">Agronomicon</p>
      <h2 className="side-title">Terenurile tale</h2>
      <p className="note">Cele cu probleme sunt primele.</p>
      <${SensorList} sensors=${sensors} selected=${selected} onSelect=${select} />
      <div className="side-foot">
        <${DemoMenu} sensorName=${sensor && sensor.name} onRun=${runDemo} />
        <p className=${'conn ' + (up ? 'up' : data.state === 'loading' ? '' : 'down')}>
          ${up ? 'Se actualizează singur' : TROUBLE[data.state][0]}</p>
      </div>
    </aside>

    <main className="sheet">
      ${!sensor ? html`<div className="blank"><h1>${TROUBLE[data.state][0]}</h1><p>${TROUBLE[data.state][1]}</p></div>`
      : html`
        <header className="sheet-head">
          <h1>${sensor.name}</h1>
          <p className="sheet-meta">${CROP[sensor.crop] || sensor.crop || ''}</p>
        </header>
        <${SensorSheet} key=${sensor.id} sensor=${sensor} readings=${own ? data.readings : []} minutes=${minutes} onMinutes=${setMinutes}
                        alerts=${own ? data.alerts : []} />`}
    </main>

    <p className="toast" role="status">${toast}</p>
  </div>`;
}

ReactDOM.createRoot(document.getElementById('root')).render(html`<${App} />`);
