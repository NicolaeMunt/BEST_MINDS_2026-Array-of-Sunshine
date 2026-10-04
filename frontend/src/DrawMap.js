// The administrator draws a field's outline: a click adds a corner, a corner can be dragged, a right click removes
// it. The satellite photo as background helps to follow the field's edges.
import { html, useEffect, useRef, useState } from './lib.js';
import { TILES, TILES_ATTRIBUTION } from './ParcelMap.js';

const PHOTO_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const PHOTO_ATTRIBUTION = 'Imagini © Esri, Maxar, Earthstar Geographics';
const START = [47.38, 28.82];  // near Orhei, where the demo parcels are
// The satellite job reads one Sentinel-2 tile (35TPN, imagery/fetch.py); roughly this box. Outside it a field is on
// the map but gets no satellite pictures.
const SATELLITE_AREA = { lat: [46.95, 47.93], lon: [28.33, 29.79] };

const round = v => Math.round(v * 1e6) / 1e6;

/** Area of an outline of [lat, lon] corners, in ares (the same flat approximation as backend/app/accounts.py). */
export function outlineAri(points) {
  if (points.length < 3) return 0;
  const lat0 = points.reduce((s, p) => s + p[0], 0) / points.length * Math.PI / 180;
  const xy = points.map(([lat, lon]) => [lon * 111320 * Math.cos(lat0), lat * 110540]);
  const twice = xy.reduce((s, [x1, y1], i) => { const [x2, y2] = xy[(i + 1) % xy.length]; return s + x1 * y2 - x2 * y1; }, 0);
  return Math.abs(twice) / 2 / 100;
}

export function inSatelliteArea(points) {
  return points.every(([lat, lon]) => lat >= SATELLITE_AREA.lat[0] && lat <= SATELLITE_AREA.lat[1]
    && lon >= SATELLITE_AREA.lon[0] && lon <= SATELLITE_AREA.lon[1]);
}

/** Pasted text -> [[lat, lon], ...]; one corner per line, "47.3812, 28.8204" or "47,3812; 28,8204".
 * Pairs written as lon, lat (28..., 47...) are turned round. Throws with the line that cannot be read. */
export function parseCorners(text) {
  const out = [];
  text.split(/\r?\n/).forEach((line, i) => {
    if (!line.trim()) return;
    const nums = (line.match(/-?\d+(?:[.,]\d+)?/g) || []).map(n => Number(n.replace(',', '.')));
    if (nums.length !== 2) throw new Error(`Rândul ${i + 1} nu are două numere: „${line.trim()}”.`);
    let [a, b] = nums;
    if (a < 35 && b > 40) [a, b] = [b, a];  // lon, lat -> lat, lon
    out.push([round(a), round(b)]);
  });
  return out;
}

export function cornersText(points) {
  return points.map(([lat, lon]) => `${lat}, ${lon}`).join('\n');
}

/** frame: change it to fit the map to the outline (after pasting coordinates). */
export function DrawMap({ id, points, onChange, frame, invalid }) {
  const ref = useRef(null), map = useRef(null), bases = useRef(null), drawn = useRef(null);
  const latest = useRef({ points, onChange });
  latest.current = { points, onChange };
  const [base, setBase] = useState('photo');

  useEffect(() => {
    const m = L.map(ref.current, { scrollWheelZoom: false, doubleClickZoom: false, zoomSnap: 0.5 });
    map.current = m;
    bases.current = {
      photo: L.tileLayer(PHOTO_TILES, { maxZoom: 19, attribution: PHOTO_ATTRIBUTION }),
      map: L.tileLayer(TILES, { maxZoom: 19, attribution: TILES_ATTRIBUTION }),
    };
    bases.current.photo.addTo(m);
    m.on('click', e => {
      const { points: now, onChange: change } = latest.current;
      change([...now, [round(e.latlng.lat), round(e.latlng.lng)]]);
    });
    if (points.length) m.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 17 });
    else m.setView(START, 13);
    const resize = new ResizeObserver(() => m.invalidateSize());
    resize.observe(ref.current);
    return () => { resize.disconnect(); m.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    Object.entries(bases.current).forEach(([key, layer]) => (key === base ? layer.addTo(map.current) : layer.remove()));
  }, [base]);

  useEffect(() => {
    if (frame && points.length) map.current.flyToBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 17, duration: 0.8 });
  }, [frame]);

  // The outline and its corners, drawn again whenever the corners change.
  useEffect(() => {
    if (drawn.current) drawn.current.remove();
    const group = L.layerGroup();
    const shape = points.length >= 2 && L.polygon(points, { color: '#E9A800', weight: 3, fillColor: '#E9A800',
      fillOpacity: points.length >= 3 ? 0.2 : 0, interactive: false, className: 'outline-shape' }).addTo(group);
    points.forEach((p, i) => {
      const corner = L.marker(p, { draggable: true, keyboard: false, title: `Colțul ${i + 1}: trage-l ca să-l muți, clic dreapta îl șterge`,
        icon: L.divIcon({ className: 'corner' + (i === 0 ? ' corner-first' : ''), iconSize: [18, 18], html: `<span>${i + 1}</span>` }) });
      corner.on('drag', e => {  // the outline follows the corner while it moves
        if (shape) shape.setLatLngs(latest.current.points.map((q, j) => (j === i ? e.target.getLatLng() : q)));
      });
      corner.on('dragend', e => {
        const ll = e.target.getLatLng();
        latest.current.onChange(latest.current.points.map((q, j) => (j === i ? [round(ll.lat), round(ll.lng)] : q)));
      });
      corner.on('contextmenu', () => latest.current.onChange(latest.current.points.filter((_, j) => j !== i)));
      corner.addTo(group);
    });
    group.addTo(map.current);
    drawn.current = group;
  }, [points]);

  return html`<div className=${'draw-map-wrap' + (invalid ? ' is-invalid' : '')} id=${id} tabIndex="-1">
    <div ref=${ref} className="draw-map" role="application"
         aria-label="Harta pe care desenezi conturul terenului: clic pe fiecare colț"></div>
    <div className="map-switch" role="group" aria-label="Fundalul hărții">
      <button type="button" aria-pressed=${base === 'photo'} onClick=${() => setBase('photo')}>Satelit</button>
      <button type="button" aria-pressed=${base === 'map'} onClick=${() => setBase('map')}>Hartă</button>
    </div>
    ${points.length === 0 && html`<p className="draw-hint">Fă clic pe fiecare colț al terenului, pe rând</p>`}
  </div>`;
}

export { SATELLITE_AREA };
