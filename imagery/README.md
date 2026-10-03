# imagery: pipeline-ul de imagini satelitare

Pentru fiecare parcelă și fiecare scenă Sentinel-2 din cache, calculează cât din parcelă are vegetație
slabă, unde e zona și cum s-a schimbat față de poza anterioară. Produce și două imagini pentru hartă:
overlay-ul cu zonele slabe și poza color reală. Deciziile și motivele lor sunt în [LOGIC.md](LOGIC.md).

## Cum rulează în aplicație

API-ul (`backend/`) rulează singur acest pipeline: în fiecare seară la 21:00, la pornire (dacă ultima
rulare bună e mai veche de o zi) și la `POST /imagery/refresh`. Pașii unei rulări:

1. API-ul scrie parcelele din baza de date în `parcels.geojson`; fișierul e generat, nu e în git.
2. Pornește `fetch.py --parcels --from <1 mai>`. Acesta descarcă doar scenele noi; ce e deja pe disc nu
   se mai descarcă.
3. Pornește `analyze.py`.
4. Salvează `out/imagery.json` în baza de date.

Pipeline-ul rulează cu Python-ul lui (`.venv`, cu rasterio), separat de API. Detaliile despre tabele și
endpoint-uri sunt în [README-ul principal](../README.md).

## Cum rulezi de mână

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

.venv\Scripts\python.exe fetch.py --parcels --from 2026-05-01   # singurul pas cu internet: tot sezonul, până azi
.venv\Scripts\python.exe analyze.py                           # fără internet, ~30 de secunde pentru 5 parcele
.venv\Scripts\python.exe analyze.py --check-images            # plus imaginile de control out/<parcel>/mask.png, weak.png
.venv\Scripts\python.exe check_map.py                         # opțional: verifică alinierea pe hartă, ca în Leaflet
.venv\Scripts\python.exe season_chart.py                      # opțional: graficul sezonului, out/<parcel>/season.png
.venv\Scripts\python.exe push.py                              # opțional: trimite rezultatul la API (POST /imagery/import)
```

Fără `parcels.geojson` (exportul API-ului), scripturile citesc `../backend/data/parcels.geojson`, fișierul
din care se încarcă baza de date. Alt fișier se poate da prin variabila `PARCELS_FILE`.

**Descărcarea** merge dată cu dată, cu toate parcelele odată. Parcelele vecine folosesc aceleași bucăți
ale fișierelor satelitului, iar GDAL le ține în memorie, deci se descarcă o singură dată. Pentru scenele
în care sub 50% din parcelă poate fi senin se citește doar harta de nori; benzile nu se mai descarcă, iar
scena apare în `skipped`. Tot sezonul pentru 5 parcele noi durează ~9 minute.

`cache/` e în git, deci analiza merge fără internet.

**Parcelă nouă:**
1. Developerul adaugă poligonul (lon/lat) în `backend/data/parcels.geojson`, cu `parcel_id` (numărul
   cadastral), `name`, `crop` și `user_id`.
2. Repornește API-ul, care încarcă parcela în bază.
3. La următoarea rulare, parcela primește tot sezonul, de la 1 mai.

Parcela trebuie să fie în tile-ul Sentinel-2 35TPN (zona Orhei). Conturul se desenează **în interiorul
câmpului** și pe **un singur lot** (vezi LOGIC.md: K10 și grâul au arătat ce se întâmplă altfel).

## Ce produce

- `out/imagery.json`: rezultatele, vezi mai jos.
- `out/overlays/<parcel>_<date>.png`: overlay-ul transparent cu zonele slabe.
- `out/overlays/<parcel>_<date>_rgb.png`: poza color, cu aceleași colțuri ca overlay-ul.
- `out/<parcel>/*.png`: imagini de control pentru oameni (masca de nori, zonele slabe, harta, sezonul).

## Formatul `out/imagery.json`

```json
{
  "rules_version": "bb8e95634d",
  "results": [
    {
      "parcel_id": "6401307.101",
      "scene_date": "2026-06-28",
      "scene_id": "S2C_35TPN_20260628_0_L2A",
      "ndvi_median": 0.783,
      "ndmi_median": 0.236,
      "affected_pct": 0.9,
      "affected_sector": "NW",
      "zone_count": 2,
      "zone_center": [28.864145, 47.405436],
      "valid_pct": 100.0,
      "prev_scene_date": "2026-06-25",
      "median_change": -0.015,
      "declined_pct": 0.0,
      "ndmi_change": 0.0,
      "zone_confirmed": true,
      "overlay_path": "/overlays/6401307.101_2026-06-28.png",
      "photo_path": "/overlays/6401307.101_2026-06-28_rgb.png",
      "overlay_bounds": [47.396738, 28.860386, 47.407506, 28.873028],
      "warnings": []
    }
  ],
  "skipped": [
    {"parcel_id": "6401307.101", "scene_date": "2026-07-28", "scene_id": "S2C_35TPN_20260728_0_L2A",
     "valid_pct": 24.6, "reason": "only 24.6% of the parcel is cloud-free (minimum 50%)"}
  ]
}
```

| Câmp | Ce înseamnă |
|---|---|
| `rules_version` | Amprenta codului de analiză (`analyze.py`, `common.py`). Se schimbă când se schimbă o regulă, ca istoricul din bază să știe cu ce reguli a fost calculat fiecare rând. |
| `parcel_id` | Numărul cadastral al parcelei (fictiv în demo). |
| `scene_id` | Scena Sentinel-2 din care vine rezultatul. |
| `ndvi_median` | NDVI-ul tipic al parcelei în acea scenă (mediana pixelilor curați). |
| `ndmi_median` | NDMI-ul tipic al parcelei: apa din frunze (nu din sol). Doar context, fără etichetă de stres de apă. |
| `affected_pct` | Procentul din partea vizibilă a parcelei aflat în zone slabe: NDVI cu peste 0,10 sub `ndvi_median`, în zone de cel puțin 10 pixeli (0,1 ha). |
| `affected_sector` | Unde e zona slabă cea mai mare, ca direcție de la centrul parcelei: `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW`; `C` = centru; `scattered` = mai multe zone fără una dominantă; `null` = nicio zonă. |
| `zone_count` | Numărul de zone slabe. |
| `zone_center` | `[lon, lat]` al pixelului din zona cea mai mare aflat cel mai aproape de centrul ei (deci mereu pe zonă), pentru un marcaj pe hartă; `null` când nu e nicio zonă sau sectorul e `scattered`. |
| `valid_pct` | Procentul din parcelă rămas după masca de nori (după ce parcela e micșorată cu 20 m de la margine). |
| `prev_scene_date` | Data scenei acceptate anterioare a parcelei, cu care se compară; `null` la prima scenă. |
| `median_change` | Cât s-a schimbat `ndvi_median` față de scena anterioară; sub −0,10 apare avertismentul „toată parcela a scăzut”. |
| `ndmi_change` | Cât s-a schimbat `ndmi_median` față de scena anterioară; `null` la prima scenă. |
| `declined_pct` | Procentul de pixeli care au scăzut cu peste 0,10 mai mult decât mediana parcelei (zone de cel puțin 10 pixeli). |
| `zone_confirmed` | `true` dacă zona principală se suprapune cu pixeli slabi ai scenei anterioare; `false` = neconfirmată (inclusiv când scena anterioară n-a văzut locul din cauza norilor); `null` la prima scenă, fără zone sau la `scattered`. |
| `overlay_path`, `photo_path` | Căile imaginilor; API-ul servește `out/overlays/` la `/overlays/`. |
| `overlay_bounds` | `[sud, vest, nord, est]`, marginile exacte ale ambelor imagini. Leaflet: `L.imageOverlay(url, [[S, V], [N, E]])`. |
| `warnings` | Listă de obiecte `{"code": ..., "text": ...}`. Scorul citește doar `code`; `text` e pentru oameni. |

| Cod de avertisment | Când apare |
|---|---|
| `low_pixel_count` | sub 200 de pixeli în parcelă după micșorarea de 20 m |
| `low_vegetation` | mediana NDVI sub 0,6 (început de sezon sau câmp recoltat; regula de pixel slab e validată la ~0,75) |
| `possible_cloud` | o zonă slabă sau înrăutățită la sub 100 m de pixeli aruncați de masca de nori |
| `whole_field_drop` | mediana NDVI a scăzut cu peste 0,10 față de scena anterioară |
| `stale_previous` | scena anterioară e la peste 30 de zile |

`skipped` conține scenele în care sub 50% din parcelă e vizibil. În bază merg în `imagery_skipped`, nu ca
rezultate, iar API-ul le arată la data aleasă ca „aici au fost nori”.

În API aceleași câmpuri ies în camelCase (`ndviMedian`, `affectedPct`, …), ca restul API-ului.

## Fișiere

| Fișier | Rol |
|---|---|
| `fetch.py` | Descarcă din Earth Search doar fereastra fiecărei parcele, în `cache/`. Singurul pas cu internet. |
| `analyze.py` | Tot pipeline-ul de analiză, doar din `cache/`. |
| `common.py` | Citirea cache-ului, a parcelelor și funcții comune. |
| `push.py` | Trimite `out/imagery.json` la API, pentru o rulare de mână. |
| `check_map.py` | Verifică alinierea pe hartă, ca în Leaflet. |
| `season_chart.py` | Graficul sezonului fiecărei parcele, doar din `imagery.json`. |
| `parcel_preview.py` | Imagini de control ale unei parcele, înainte de analiză. |
| `area_preview.py`, `measure_*.py` | Studiile din spatele deciziilor (alegerea parcelelor, masca, pragul, sectorul, overlay-ul). Nu fac parte din pipeline și rămân pe datele pe care s-au luat deciziile (`common.STUDY_DATES`). |
| `candidates.geojson` | Câmpurile măsurate când am ales prima parcelă (J4). |
| `../backend/data/parcels.geojson` | Parcelele, din care se încarcă baza de date. |
| `../backend/app/imagery.py` | Partea din API care rulează pipeline-ul zilnic și îi salvează rezultatele. |
