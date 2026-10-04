// All the fields on one small map, coloured like the list: where to go today. A click opens the field.
import { html, useEffect, useRef } from './lib.js';
import { verdict } from './labels.js';
import { centroid, latLngs } from './satellite.js';
import { useLeaflet } from './ParcelMap.js';

const COLOR = { ok: '#2E6B3E', warning: '#E9A800', critical: '#8C1D40', no_data: '#7C8882' };

export function OverviewMap({ parcels, sensors, selected, onSelect }) {
  const [ref, map] = useLeaflet({ zoomControl: false, attributionControl: false }, () => {});
  const layers = useRef(null), framed = useRef(false);

  useEffect(() => {
    if (!parcels.length) return;
    if (layers.current) layers.current.remove();
    const group = L.featureGroup();
    for (const p of parcels) {
      const sensor = sensors.find(s => s.id === p.parcelId);
      const status = sensor ? verdict(sensor).status : 'no_data';
      const chosen = p.parcelId === selected;
      const label = `${p.name}${sensor ? ': ' + verdict(sensor).word : ''}`;
      L.polygon(latLngs(p.geometry), { color: COLOR[status], weight: 2, fillColor: COLOR[status], fillOpacity: 0.55 })
        .bindTooltip(label).on('click', () => onSelect(p.parcelId)).addTo(group);
      // The fields are small at this zoom: a dot in the field's colour marks each one.
      L.circleMarker(centroid(p.geometry), { radius: chosen ? 9 : 7, color: chosen ? '#1D2420' : '#fff', weight: chosen ? 3 : 2,
        fillColor: COLOR[status], fillOpacity: 1 })
        .bindTooltip(label).on('click', () => onSelect(p.parcelId)).addTo(group);
    }
    group.addTo(map.current);
    layers.current = group;
    if (!framed.current) {
      // After the layout has given the map its size, or the zoom comes out wrong.
      framed.current = true;
      const bounds = group.getBounds();
      setTimeout(() => { if (map.current) { map.current.invalidateSize(); map.current.fitBounds(bounds, { padding: [16, 16] }); } }, 50);
    }
  }, [parcels, sensors, selected]);

  return html`<div ref=${ref} className="overview-map" role="img"
    aria-label="Harta cu toate terenurile, colorate după starea lor"></div>`;
}
