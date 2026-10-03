# imagery: pipeline-ul de imagini satelitare

Pentru fiecare parcelă din `parcels.geojson` și fiecare scenă Sentinel-2 din cache, calculează cât
din parcelă are vegetație slabă, unde e zona și produce două imagini pentru hartă: overlay-ul cu
zonele slabe și poza color reală. Deciziile și motivele lor sunt în [LOGIC.md](LOGIC.md).

## Cum rulezi

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

.venv\Scripts\python.exe fetch.py --parcels parcels.geojson   # singurul pas cu internet; ce e pe disc nu se mai descarcă
.venv\Scripts\python.exe analyze.py                           # fără internet, câteva secunde
.venv\Scripts\python.exe check_map.py                         # opțional: verifică alinierea pe hartă
.venv\Scripts\python.exe season_chart.py                      # opțional: graficul sezonului, out/<parcel>/season.png
```

Tot sezonul în loc de datele implicite: `fetch.py --parcels parcels.geojson --from 2026-05-01 --to 2026-07-31`.
Scenele în care sub 50% din parcelă poate fi senin nu-și descarcă benzile (apar în `skipped`).

`cache/` e în git, deci demo-ul merge direct cu `analyze.py`, fără internet.

**Parcelă nouă:** adaugi poligonul (lon/lat, cu `"parcel_id"` în `properties`) în `parcels.geojson`,
rulezi `fetch.py` (~15 s și ~14 MB pe dată), apoi `analyze.py`. Parcela trebuie să fie în tile-ul
Sentinel-2 35TPN (zona Orhei).

## Ce produce

- `out/imagery.json`: rezultatele, vezi mai jos.
- `out/overlays/<parcel>_<date>.png`: overlay-ul transparent cu zonele slabe.
- `out/overlays/<parcel>_<date>_rgb.png`: poza color, cu aceleași colțuri ca overlay-ul.
- `out/<parcel>/*.png`: imagini de control pentru noi (masca de nori, zonele slabe, harta).

## Formatul `out/imagery.json`

```json
{
  "results": [
    {
      "parcel_id": "demo1",
      "scene_date": "2026-06-28",
      "ndvi_median": 0.783,
      "ndmi_median": 0.236,
      "affected_pct": 0.9,
      "affected_sector": "NW",
      "zone_count": 2,
      "zone_center": [28.864145, 47.405436],
      "valid_pct": 100.0,
      "prev_scene_date": null,
      "median_change": null,
      "ndmi_change": null,
      "zone_confirmed": null,
      "declined_pct": null,
      "overlay_path": "/overlays/demo1_2026-06-28.png",
      "photo_path": "/overlays/demo1_2026-06-28_rgb.png",
      "overlay_bounds": [47.396738, 28.860386, 47.407506, 28.873028],
      "warnings": []
    }
  ],
  "skipped": [
    {"parcel_id": "demo1", "scene_date": "2026-07-28", "valid_pct": 24.6,
     "reason": "only 24.6% of the parcel is cloud-free (minimum 50%)"}
  ]
}
```

| Câmp | Ce înseamnă |
|---|---|
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
| `overlay_path`, `photo_path` | Căile imaginilor; serverul trebuie să servească folderul `out/overlays/` la `/overlays/`. |
| `overlay_bounds` | `[sud, vest, nord, est]`, marginile exacte ale ambelor imagini. Leaflet: `L.imageOverlay(url, [[S, V], [N, E]])`. |
| `warnings` | Listă de obiecte `{"code": ..., "text": ...}`. Scorul citește doar `code`; `text` e pentru oameni. Codurile sunt în tabelul de mai jos. |

| Cod de avertisment | Când apare |
|---|---|
| `low_pixel_count` | sub 200 de pixeli în parcelă după micșorarea de 20 m |
| `low_vegetation` | mediana NDVI sub 0,6 (început de sezon; regula de pixel slab e validată la ~0,75) |
| `possible_cloud` | o zonă slabă sau înrăutățită la sub 100 m de pixeli aruncați de masca de nori |
| `whole_field_drop` | mediana NDVI a scăzut cu peste 0,10 față de scena anterioară |
| `stale_previous` | scena anterioară e la peste 30 de zile |

`skipped` conține scenele în care sub 50% din parcelă e vizibil. Ele **nu** se trimit la server ca
rezultate.

**De anunțat echipei, față de contractul inițial:** câmpurile noi `zone_count`, `zone_center`,
`prev_scene_date`, `median_change`, `declined_pct`, `ndmi_median`, `ndmi_change`, `zone_confirmed` și
`warnings` (cu coduri fixe); lista separată `skipped`; valorile `C`, `scattered` și `null` pentru `affected_sector`.

## Fișiere

| Fișier | Rol |
|---|---|
| `fetch.py` | Descarcă din Earth Search doar fereastra fiecărei parcele, în `cache/`. |
| `analyze.py` | Tot pipeline-ul de analiză, doar din `cache/`. |
| `common.py` | Citirea cache-ului și funcții comune. |
| `check_map.py` | Verifică alinierea pe hartă, ca în Leaflet. |
| `season_chart.py` | Graficul sezonului unei parcele, doar din `imagery.json`. |
| `parcel_preview.py` | Imagini de control ale unei parcele, înainte de analiză. |
| `area_preview.py`, `measure_*.py` | Studiile din spatele deciziilor (alegerea parcelei, masca, pragul, sectorul, overlay-ul). Nu fac parte din pipeline. |
| `parcels.geojson` | Parcelele analizate; `candidates.geojson` sunt câmpurile măsurate la alegerea parcelei demo. |
