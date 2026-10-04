// One field on the map: the satellite picture of the chosen day, its weak zones in red, the main zone and the sensor.
// Leaflet draws into a plain div; React only hands it the layers to show.
import { html, useEffect, useRef, useState, API } from './lib.js';
import { centroid, latLngs, longDay } from './satellite.js';

// OpenStreetMap needs the internet; without it the map keeps the satellite picture on a plain background.
export const TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
export const TILES_ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Sentinel-2: Copernicus';
const BLUE = '#1C5D99';
const FADE_MS = 450;  // the new picture fades in over the old one, which goes once the new one is there

/** The Leaflet map of a div, made once; onOffline is called when the background tiles cannot load. */
export function useLeaflet(options, onOffline) {
  const ref = useRef(null), map = useRef(null);
  useEffect(() => {
    map.current = L.map(ref.current, { scrollWheelZoom: false, ...options });
    L.tileLayer(TILES, { maxZoom: 19, attribution: TILES_ATTRIBUTION }).on('tileerror', onOffline).addTo(map.current);
    const resize = new ResizeObserver(() => map.current && map.current.invalidateSize());
    resize.observe(ref.current);
    return () => { resize.disconnect(); map.current.remove(); map.current = null; };
  }, []);
  return [ref, map];
}

export function ParcelMap({ parcel, result, showPhoto, showZones }) {
  const [offline, setOffline] = useState(false);
  const [ref, map] = useLeaflet({ zoomSnap: 0.25 }, () => setOffline(true));
  const layers = useRef(null);

  // Frame the field once: the picture's corners, with the ground around it.
  useEffect(() => {
    const bounds = L.polygon(latLngs(parcel.geometry)).getBounds();
    map.current.fitBounds(bounds, { padding: [30, 30] });
    const later = setTimeout(() => { if (map.current) { map.current.invalidateSize(); map.current.fitBounds(bounds, { padding: [30, 30] }); } }, 50);
    return () => clearTimeout(later);
  }, [parcel.parcelId]);

  useEffect(() => {
    const old = layers.current;
    const group = L.layerGroup();
    const pictures = [];
    if (result) {
      const [s, w, n, e] = result.overlayBounds, bounds = [[s, w], [n, e]];
      if (showPhoto) pictures.push(L.imageOverlay(API + result.photoPath, bounds, { alt: 'Poza din satelit a câmpului', opacity: 0 }));
      if (showZones) pictures.push(L.imageOverlay(API + result.overlayPath, bounds, { alt: 'Zonele slabe, în roșu', opacity: 0 }));
    }
    pictures.forEach(p => p.addTo(group));
    L.polygon(latLngs(parcel.geometry), { color: '#fff', weight: 2, fill: false, dashArray: '6 4', interactive: false }).addTo(group);
    L.circleMarker(centroid(parcel.geometry), { radius: 7, color: '#fff', weight: 2, fillColor: BLUE, fillOpacity: 1 })
      .bindTooltip('Senzorul de pe teren').addTo(group);
    if (result && result.zoneCenter && showZones) {
      L.marker([result.zoneCenter[1], result.zoneCenter[0]], { keyboard: false,
        icon: L.divIcon({ className: 'zone-pin', iconSize: [22, 22], html: '<span></span>' }) })
        .bindTooltip('Zona slabă cea mai mare').addTo(group);
    }
    group.addTo(map.current);
    layers.current = group;

    // Each picture fades in once loaded (CSS transition on its opacity); the old layers go when the new pictures
    // are in, so the map never flashes empty between two days.
    let left = pictures.length, timer;
    const done = () => { timer = setTimeout(() => old && old.remove(), FADE_MS); };
    pictures.forEach(p => {
      const show = () => { p.setOpacity(1); if (--left === 0) done(); };
      p.once('load', show).once('error', show);
    });
    if (!pictures.length) { if (old) old.remove(); }
    const fallback = setTimeout(() => { pictures.forEach(p => p.setOpacity(1)); if (old) old.remove(); }, 3000);
    // Another day chosen before this one finished: the old layers go now; this group stays until the next one is in.
    return () => { clearTimeout(timer); clearTimeout(fallback); if (old) old.remove(); };
  }, [parcel.parcelId, result, showPhoto, showZones]);

  return html`<div className="map-wrap">
    <div ref=${ref} className="parcel-map" role="img"
         aria-label=${result ? `Harta câmpului cu poza din satelit din ${result.sceneDate}` : 'Harta câmpului'}></div>
    ${result && html`<p className="map-badge" key=${result.sceneDate}><i></i>Poza din ${longDay(result.sceneDate)}</p>`}
    ${offline && html`<p className="note map-offline">Fără internet: lipsește harta de fundal; poza din satelit rămâne.</p>`}
  </div>`;
}
