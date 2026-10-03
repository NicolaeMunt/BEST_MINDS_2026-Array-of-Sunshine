# Crop Monitor API (Coder 3)

Берёт показания датчиков, уровень заморозка и оповещения из сервиса **sensors-alerts** (Coder 2,
`../sensors-alerts`), сохраняет показания с метками времени в SQLite и отдаёт всё веб-приложению.
Участки, отчёты дрона и почвы и оценка приоритетов пока убраны: они вернутся вместе с экраном участка.

```
frontend ──> Crop Monitor API :8000 ──> sensors-alerts :8081  (показания, OK/WARNING/CRITICAL, оповещения, демо)
                    │
                    └── SQLite (sensors.db): показания датчиков с метками времени
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
   uvicorn app.main:app --port 8000      # sensors.db создаётся сам
   ```

Веб-приложение: http://localhost:8000/ (→ `/app/`, `?parcel=P2` открывает датчик P2),
мобильный прототип — `/app/AgroMonitor.html`. Swagger: http://localhost:8000/docs

| Переменная | По умолчанию | |
|---|---|---|
| `SENSORS_URL` | `http://localhost:8081` | адрес sensors-alerts |
| `SENSORS_TIMEOUT_SEC` | `2` | таймаут запросов к нему |
| `DB_PATH` | `backend/sensors.db` | файл базы |
| `COLLECT_INTERVAL_SEC` | `5` | как часто показания копируются в базу |
| `CORS_ORIGINS` | `localhost` / `127.0.0.1` на портах 5173, 3000, 5500 | origin фронтенда через запятую, `*` — любой |

Список датчиков (ID `P1`, `P2`, …, название, культура) задаётся в `app.parcels` в
`sensors-alerts/src/main/resources/application.yml`.
JSON-поля в camelCase, поля датчиков — как в общем контракте (`temperatureC`, `humidityPct`, `dewPointC`, `frostLevel`).
Тексты для пользователя — на румынском.

## Хранение показаний

sensors-alerts держит в памяти только последние показания. `app/collector.py` раз в 5 секунд забирает
новые и пишет их в таблицу `sensor_readings`:

| Колонка | |
|---|---|
| `parcel_id` | ID датчика, как в sensors-alerts |
| `timestamp` | когда датчик измерил (UTC, `2026-10-03T14:24:41.600Z`) |
| `temperature_c`, `humidity_pct` | показание |
| `received_at` | когда API его сохранил; при реплее отличается от `timestamp` |

Первичный ключ — `(parcel_id, timestamp)`: повторная запись того же показания его заменяет, дублей нет.
«Последние N минут» отсчитываются от показания, сохранённого последним, поэтому во время реплея
(метки времени 2020 года) график показывает реплей, а после него — снова текущие показания.

## Эндпоинты

| | |
|---|---|
| `GET /sensors/parcels` | датчики (`id`, `name`, `crop`) с последним показанием в `latest` (`null`, пока показаний нет) |
| `GET /sensors/parcels/{id}/latest` | контракт sensors-alerts + `mode`, `dropLastHourC`, `frost` (приоритет, рекомендация, причины) |
| `GET /sensors/parcels/{id}/readings?minutes=60` | сохранённые показания из базы + `dewPointC`; до 7 суток, не больше 300 точек (равномерно прорежены) |
| `GET /alerts?parcelId={id}` | контракт + `priority`, `title`; уровень `OK` — отбой тревоги |
| `POST /demo/{frost\|humid\|dry\|replay\|normal}/{parcelId}` | → sensors-alerts: режим симулятора |
| `POST /demo/reset` | → sensors-alerts: всё в NORMAL, оповещения и cooldowns очищены |

Если sensors-alerts не отвечает, эндпоинты `/sensors/parcels`, `latest`, `/alerts` и `/demo` возвращают `503`;
`readings` продолжает отдавать то, что уже сохранено.

`GET /sensors/parcels/P1/latest`:
```jsonc
{ "parcelId": "P1", "timestamp": "2026-10-03T14:24:41.6Z", "temperatureC": -2.8, "humidityPct": 57,
  "dewPointC": -10.1, "frostLevel": "CRITICAL",          // OK | WARNING | CRITICAL (из sensors-alerts)
  "crop": "orchard", "humidityLevel": "OK",              // OK | LOW | HIGH для культуры
  "mode": "REPLAY",                                       // NORMAL | FROST | HUMID | DRY | REPLAY
  "dropLastHourC": 1.2,                                   // на сколько холоднее, чем час назад
  "frost": { "frostLevel": "CRITICAL", "score": 95, "priority": "high", "title": "Îngheț",
             "message": "Pornește imediat protecția ...",
             "reasons": [{ "code": "black_frost", "text": "Aer uscat (punct de rouă -10.1°C) — ...", "source": "sensor" }] } }
```

## Логика заморозка

`app/frost.py`: уровень берётся из sensors-alerts, API добавляет приоритет (WARNING → medium,
CRITICAL → high), рекомендацию и причины: ниже/около нуля, остывание за последний час, иней или
«чёрный» заморозок (сухой воздух, точка росы далеко ниже температуры).

`data/frost-night-chisinau-2020-04-01.csv` — реальная ночь с заморозком (Кишинёв, 1–2 апреля 2020, до −4°C)
в формате реплея sensors-alerts. Источник: Open-Meteo Historical Weather API (ERA5), CC BY 4.0.
