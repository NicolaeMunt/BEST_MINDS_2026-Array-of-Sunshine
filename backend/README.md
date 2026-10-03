# Crop Monitor API (Coder 3)

Хранит участки, показания датчиков и результаты двух модулей (дрон + почва/погода), объединяет их в оценку:
статус, health score, уровень заморозка, список действий с приоритетом и причинами, оповещения.

## Запуск

```bash
cd backend
pip install -r requirements.txt
python seed.py                      # демо-участок + час истории датчиков (пересоздаёт agro.db)
uvicorn app.main:app --reload --port 8000
```

Swagger со всеми схемами: http://localhost:8000/docs
Веб-приложение (из `../frontend`): http://localhost:8000/ → `/app/AgroMonitorWeb.html`, мобильный прототип — `/app/AgroMonitor.html`.
Тексты для пользователя (причины, рекомендации, оповещения) — на румынском, как во фронтенде.

| Переменная | По умолчанию | |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000` | origin фронтенда через запятую, `*` — любой |
| `SIMULATOR` | `1` | `0` — выключить встроенный симулятор датчиков (если показания шлют реальные датчики) |
| `SENSOR_TICK_SEC` | `3` | как часто симулятор пишет показание |
| `ALERT_COOLDOWN_SEC` | `600` | повтор оповещения того же уровня не чаще; повышение уровня проходит сразу |

Все JSON-поля в camelCase (общий контракт). Входящие запросы принимают и snake_case.

## Фронтенд

| | |
|---|---|
| `GET /parcels` | участки с оценкой (сейчас один). `GET /parcels/{id}` — один |
| `GET /sensors/parcels/{id}/latest` | последнее показание + точка росы + уровень заморозка (с приоритетом и причинами) |
| `GET /sensors/parcels/{id}/readings?minutes=60` | показания за N минут, от старых к новым — для графика |
| `GET /alerts?parcelId={id}` | недавние оповещения, новые первыми (`parcelId` необязателен, `limit` до 500) |
| `POST /demo/frost/{parcelId}` | режим FROST: температура падает до −4°C примерно за минуту |
| `POST /demo/replay/{parcelId}` | воспроизведение реальной ночи с заморозком (1–2 апреля 2020, Кишинёв, −4°C), ~3 мин |
| `POST /demo/reset` | все участки в NORMAL, оповещения и cooldowns очищены |

`GET /sensors/parcels/1/latest`:
```jsonc
{ "parcelId": 1, "mode": "FROST",                  // NORMAL | FROST | REPLAY
  "timestamp": "2026-10-03T12:25:51Z", "temperature": -2.3, "humidity": 85, "windSpeed": 0.6,
  "soilTemperature": -0.4, "dewPoint": -4.5, "frostLevel": "HIGH",   // NONE | LOW | MEDIUM | HIGH
  "trend": -4.8, "predictedTemperature1h": -7.1, "source": "simulated",
  "frost": { "frostLevel": "HIGH", "score": 100, "priority": "high", "title": "Сильный заморозок",
             "message": "Срочно включите защиту от заморозка: ...",
             "reasons": [{ "code": "below_zero", "text": "Температура воздуха -2.3°C — ниже нуля", "source": "sensor" }] } }
```

`GET /alerts?parcelId=1`:
```jsonc
[{ "id": 3, "parcelId": 1, "createdAt": "...", "type": "FROST", "level": "HIGH", "priority": "high",
   "title": "Сильный заморозок", "message": "...", "reasons": [...] }]
```

`GET /parcels`:
```jsonc
{ "id": 1, "name": "Поле №1", "crop": "wheat", "areaHa": 12.5, "lat": 47.02, "lon": 28.83,
  "boundary": [[lon, lat], ...], "mode": "NORMAL",
  "sensors": { ...как /sensors/parcels/1/latest... },
  "status": "critical",            // ok | warning | critical | no_data
  "healthScore": 65,               // 0..100
  "priority": "high",              // приоритет самого срочного действия
  "summary": "Сильный заморозок — защитить посевы; Нужен полив",
  "actions": [{ "type": "protect_from_frost", "title": "...", "score": 95, "priority": "high",
                "reasons": [{ "code": "below_zero", "text": "...", "source": "sensor" }] }],
  "metrics": { "ndviMean": 0.56, "soilMoisturePct": 18, ... },
  "zones": [{ "id": "0-0", "lat": ..., "lon": ..., "ndvi": 0.68, "issue": null }],
  "updatedAt": { "vision": "...", "field": "..." } }
```

## Интеграция (Кодер 1 и Кодер 2)

Все поля необязательные — отправляйте то, что умеет ваш модуль. Лишние поля тоже сохраняются.

**Датчики** → `POST /sensors/parcels/{id}/readings` (с `SIMULATOR=0`, если симулятор не нужен)
```json
{ "timestamp": "2026-10-03T22:00:00Z", "temperature": 1.2, "humidity": 90, "windSpeed": 0.8, "soilTemperature": 2.5 }
```

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

Новый участок: `POST /parcels` с `{ "name": "...", "crop": "wheat", "lat": ..., "lon": ... }`.

## Логика оценки

**Заморозок** (`app/frost.py`): точка росы по формуле Магнуса; уровень по температуре воздуха —
`HIGH` ≤ −2°C, `MEDIUM` ≤ 0°C, `LOW` ≤ 2°C или ≤ 4°C при точке росы ≤ 0 / прогнозе на час ≤ 0.
Причины: быстрое остывание, иней или «чёрный» заморозок (сухой воздух), штиль, промёрзшая почва.
Оповещение создаётся при уровне ≥ LOW; тот же или более низкий уровень повторяется не чаще `ALERT_COOLDOWN_SEC`.

**Действия по участку** (`app/scoring.py`):

| Действие | Когда |
|---|---|
| `protect_from_frost` | уровень заморозка ≥ LOW по последнему показанию датчиков |
| `irrigate` | влажность почвы ниже нормы культуры и/или водный стресс на снимке; +жара, −дождь ≥ 10 мм; не предлагается для спелого урожая |
| `treat_disease` | болезнь с уверенностью ≥ 0.5; выше при большой площади и влажности воздуха ≥ 80% |
| `treat_pests` / `remove_weeds` | вредители ≥ 5% / сорняки ≥ 10% площади |
| `harvest` | спелость ≥ 0.75 (готовиться), ≥ 0.9 (собирать); срочнее, если идёт дождь |
| `fertilize` | низкий NDVI при нормальной влажности, без болезни и не на созревании |
| `fly_drone` / `check_sensors` | нет данных или они устарели (дрон > 7 дней, почва > 48 ч) |

Score 0..100 → `high` ≥ 70, `medium` ≥ 40, `low` ниже. Пороги по культурам — в `CROP_THRESHOLDS`.

Данные реплея: `data/frost_night.json` — Open-Meteo Historical Weather API (ERA5), CC BY 4.0.
