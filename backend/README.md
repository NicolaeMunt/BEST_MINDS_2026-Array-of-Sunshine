# Crop Monitor API (Coder 3)

Хранит участки и результаты анализа (дрон + почва/погода), берёт показания датчиков, уровень заморозка
и оповещения из сервиса **sensors-alerts** (Coder 2, `../sensors-alerts`) и объединяет всё в оценку:
статус, health score, список действий с приоритетом и причинами.

```
frontend ──> Crop Monitor API :8000 ──> sensors-alerts :8081  (показания, OK/WARNING/CRITICAL, оповещения, демо)
                    │
                    └── SQLite: участки, отчёты дрона и почвы
```

## Запуск

1. sensors-alerts (JDK 21+, Maven), с реальной ночью для реплея:
   ```powershell
   cd sensors-alerts
   $env:REPLAY_FILE = "file:../backend/data/frost-night-chisinau-2020-04-01.csv"
   $env:FROST_COOLDOWN_SECONDS = "30"    # для репетиций
   mvn spring-boot:run                   # или: java -jar target/sensors-alerts-0.1.0.jar
   ```
2. API:
   ```bash
   cd backend
   pip install -r requirements.txt
   python seed.py                        # участки P1–P3 (пересоздаёт agro.db)
   uvicorn app.main:app --port 8000
   ```

Веб-приложение: http://localhost:8000/ (→ `/app/AgroMonitorWeb.html`, `?parcel=P2` открывает участок),
мобильный прототип — `/app/AgroMonitor.html`. Swagger: http://localhost:8000/docs

| Переменная | По умолчанию | |
|---|---|---|
| `SENSORS_URL` | `http://localhost:8081` | адрес sensors-alerts |
| `SENSORS_TIMEOUT_SEC` | `2` | таймаут запросов к нему |
| `CORS_ORIGINS` | `localhost` / `127.0.0.1` на портах 5173, 3000, 5500 | origin фронтенда через запятую, `*` — любой |

ID участков (`P1`, `P2`, …) должны совпадать с `app.parcels` в `sensors-alerts/src/main/resources/application.yml`.
JSON-поля в camelCase, поля датчиков — как в общем контракте (`temperatureC`, `humidityPct`, `dewPointC`, `frostLevel`).
Тексты для пользователя — на румынском.

## Фронтенд

| | |
|---|---|
| `GET /parcels` | участки с оценкой; `GET /parcels/{id}` — один |
| `GET /sensors/parcels/{id}/latest` | контракт sensors-alerts + `mode`, `dropLastHourC`, `frost` (приоритет, рекомендация, причины) |
| `GET /sensors/parcels/{id}/readings?minutes=60` | контракт + `dewPointC` у каждой точки — для графика |
| `GET /alerts?parcelId={id}` | контракт + `priority`, `title`; уровень `OK` — отбой тревоги |
| `POST /demo/frost/{parcelId}` | → sensors-alerts: режим FROST |
| `POST /demo/replay/{parcelId}` | → sensors-alerts: реплей ночи (≈2,5 мин) |
| `POST /demo/reset` | → sensors-alerts: всё в NORMAL, оповещения и cooldowns очищены |

Если sensors-alerts не отвечает: эндпоинты датчиков возвращают `503`, а `GET /parcels` продолжает работать
(`sensors: null`, `sensorsStatus: "unavailable"` и действие `check_sensor_service`).

`GET /sensors/parcels/P1/latest`:
```jsonc
{ "parcelId": "P1", "timestamp": "2026-10-03T14:24:41.6Z", "temperatureC": -2.8, "humidityPct": 57,
  "dewPointC": -10.1, "frostLevel": "CRITICAL",          // OK | WARNING | CRITICAL (из sensors-alerts)
  "mode": "REPLAY",                                       // NORMAL | FROST | REPLAY
  "dropLastHourC": 1.2,                                   // на сколько холоднее, чем час назад
  "frost": { "frostLevel": "CRITICAL", "score": 95, "priority": "high", "title": "Îngheț",
             "message": "Pornește imediat protecția ...",
             "reasons": [{ "code": "black_frost", "text": "Aer uscat (punct de rouă -10.1°C) — ...", "source": "sensor" }] } }
```

`GET /parcels`:
```jsonc
{ "id": "P1", "name": "Livada Nord", "crop": "orchard", "areaHa": 8.2, "lat": 47.06, "lon": 28.80,
  "boundary": [[lon, lat], ...],
  "sensors": { ...как /sensors/parcels/P1/latest... }, "sensorsStatus": "ok",   // ok | no_readings | unavailable
  "status": "critical", "healthScore": 74, "priority": "high",
  "summary": "Îngheț — protejează culturile; Tratează boala (rapăn)",
  "actions": [{ "type": "protect_from_frost", "title": "...", "score": 95, "priority": "high", "reasons": [...] }],
  "metrics": { "ndviMean": 0.63, "soilMoisturePct": 27, ... },
  "zones": [{ "id": "0-0", "lat": ..., "lon": ..., "ndvi": 0.72, "issue": null }],
  "updatedAt": { "vision": "...", "field": "..." } }
```

`mode`: у sensors-alerts нет эндпоинта режима, поэтому `REPLAY` определяется по старым меткам времени,
а `FROST` — если режим включали через этот API.

## Интеграция

Все поля необязательные — отправляйте то, что умеет ваш модуль.

**Анализ снимков дрона** → `POST /parcels/{id}/vision`
```json
{ "capturedAt": "2026-10-03T10:00:00Z", "ndviMean": 0.56, "waterStressPct": 22,
  "disease": "rust", "diseaseConfidence": 0.82, "diseaseAreaPct": 9,
  "pestAreaPct": 0, "weedAreaPct": 4, "ripeness": 0.55,
  "zones": [{ "id": "0-0", "lat": 47.02, "lon": 28.83, "ndvi": 0.68, "issue": "water_stress" }] }
```

**Почва и погода** → `POST /parcels/{id}/field`
```json
{ "measuredAt": "2026-10-03T10:00:00Z", "soilMoisturePct": 18, "airTempC": 27,
  "humidityPct": 64, "tempMaxForecastC": 31, "rainForecastMm48h": 2 }
```

Новый участок: `POST /parcels` с `{ "id": "P4", "name": "...", "crop": "wheat", "lat": ..., "lon": ... }`
(без `id` генерируется следующий `P<n>`); чтобы у него были датчики, добавьте тот же ID в конфиг sensors-alerts.

## Логика оценки

**Заморозок** (`app/frost.py`): уровень берётся из sensors-alerts, API добавляет приоритет
(WARNING → medium, CRITICAL → high), рекомендацию и причины: ниже/около нуля, остывание за последний час,
иней или «чёрный» заморозок (сухой воздух, точка росы далеко ниже температуры).

**Действия по участку** (`app/scoring.py`):

| Действие | Когда |
|---|---|
| `protect_from_frost` | уровень заморозка WARNING или CRITICAL |
| `check_sensor_service` | sensors-alerts не отвечает |
| `irrigate` | влажность почвы ниже нормы культуры и/или водный стресс на снимке; +жара, −дождь ≥ 10 мм; не предлагается для спелого урожая |
| `treat_disease` | болезнь с уверенностью ≥ 0.5; выше при большой площади и влажности воздуха ≥ 80% |
| `treat_pests` / `remove_weeds` | вредители ≥ 5% / сорняки ≥ 10% площади |
| `harvest` | спелость ≥ 0.75 (готовиться), ≥ 0.9 (собирать); срочнее, если идёт дождь |
| `fertilize` | низкий NDVI при нормальной влажности, без болезни и не на созревании |
| `fly_drone` / `check_sensors` | нет данных или они устарели (дрон > 7 дней, почва > 48 ч) |

Score 0..100 → `high` ≥ 70, `medium` ≥ 40, `low` ниже. Пороги по культурам (`wheat`, `barley`, `corn`,
`sunflower`, `orchard`, `vineyard`) — в `CROP_THRESHOLDS`.

`data/frost-night-chisinau-2020-04-01.csv` — реальная ночь с заморозком (Кишинёв, 1–2 апреля 2020, до −4°C)
в формате реплея sensors-alerts. Источник: Open-Meteo Historical Weather API (ERA5), CC BY 4.0.
