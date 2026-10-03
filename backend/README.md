# Agronomicon API (Coder 3)

Берёт показания датчиков, уровень заморозка и оповещения из сервиса **sensors-alerts** (Coder 2,
`../sensors-alerts`), сохраняет показания с метками времени в SQLite и отдаёт всё веб-приложению.
Участки, отчёты дрона и почвы и оценка приоритетов пока убраны: они вернутся вместе с экраном участка.

```
frontend ──> Agronomicon API :8000 ──> sensors-alerts :8081  (показания, OK/WARNING/CRITICAL, оповещения, демо)
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

Веб-приложение: http://localhost:8000/ (→ `/app/`, `?parcel=6401204.045` открывает датчик 6401204.045),
мобильный прототип — `/app/AgroMonitor.html`. Swagger: http://localhost:8000/docs

| Переменная | По умолчанию | |
|---|---|---|
| `SENSORS_URL` | `http://localhost:8081` | адрес sensors-alerts |
| `SENSORS_TIMEOUT_SEC` | `2` | таймаут запросов к нему |
| `DB_PATH` | `backend/sensors.db` | файл базы |
| `COLLECT_INTERVAL_SEC` | `5` | как часто показания копируются в базу |
| `CORS_ORIGINS` | `localhost` / `127.0.0.1` на портах 5173, 3000, 5500 | origin фронтенда через запятую, `*` — любой |

Список датчиков (ID `6401512.058`, `6401204.045`, …, название, культура) задаётся в `app.parcels` в
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

Оповещения копируются так же, в таблицу `sensor_alerts` (датчик, время отправки, тип, уровень, показания
в тот момент и текст для фермера; ключ — `(parcel_id, timestamp, type, level)`), и `GET /alerts` читает их из базы.

## Пример сезона

Чтобы было что показать, в `data/` лежит пример сезона для пяти демо-датчиков. **Цифры придуманы, не измерены**:
поздний заморозок в мае, дождливые периоды, две волны жары и первый осенний заморозок.

| | |
|---|---|
| `data/sensor-history-sample.csv` | показания раз в час с 1 мая: `parcelId,timestamp,temperatureC,humidityPct` |
| `data/alert-history-sample.csv` | оповещения, которые эти показания вызвали бы по порогам культур |
| `python load_sample.py` | загружает оба файла в базу (можно запускать повторно); `start.ps1` делает это для новой базы |
| `python make_sample.py` | пересоздаёт файлы до вчерашнего дня; пороги культур скопированы из `application.yml` |

## Эндпоинты

| | |
|---|---|
| `GET /sensors/parcels` | датчики (`id`, `name`, `crop`) с последним показанием в `latest` (`null`, пока показаний нет) |
| `GET /sensors/parcels/{id}/latest` | контракт sensors-alerts + `mode`, `dropLastHourC`, `frost` (приоритет, рекомендация, причины) |
| `GET /sensors/parcels/{id}/readings?minutes=60` | сохранённые показания из базы + `dewPointC`. До 2 часов — сами показания (не больше 300, равномерно прорежены); дольше — по точке на 5 минут, час или день со средним и `minTemperatureC` / `maxTemperatureC` |
| `GET /alerts?parcelId={id}` | сохранённые оповещения из базы, новые первыми: контракт + `priority`, `title`; уровень `OK` — отбой тревоги |
| `POST /demo/{frost\|humid\|dry\|replay\|normal}/{parcelId}` | → sensors-alerts: режим симулятора |
| `POST /demo/reset` | → sensors-alerts: всё в NORMAL, оповещения и cooldowns очищены |

Если sensors-alerts не отвечает, эндпоинты `/sensors/parcels`, `latest` и `/demo` возвращают `503`;
`readings` и `/alerts` продолжают отдавать то, что уже сохранено.

`GET /sensors/parcels/6401512.058/latest`:
```jsonc
{ "parcelId": "6401512.058", "timestamp": "2026-10-03T14:24:41.6Z", "temperatureC": -2.8, "humidityPct": 57,
  "dewPointC": -10.1, "frostLevel": "CRITICAL",          // OK | WARNING | CRITICAL (из sensors-alerts)
  "crop": "orchard", "humidityLevel": "OK",              // OK | LOW | HIGH для культуры
  "mode": "REPLAY",                                       // NORMAL | FROST | HUMID | DRY | REPLAY
  "dropLastHourC": 1.2,                                   // на сколько холоднее, чем час назад
  "frost": { "frostLevel": "CRITICAL", "score": 95, "priority": "high", "title": "Îngheț",
             "message": "Pornește imediat protecția ...",
             "reasons": [{ "code": "black_frost", "text": "Aer uscat (punct de rouă -10.1°C) — ...", "source": "sensor" }] } }
```

## Участки и спутник

Участки (кадастровый номер, название, культура, полигон) берутся из `data/parcels.geojson` и при старте
записываются в базу (`users`, `parcels`). Модуль `app/imagery.py` раз в день запускает спутниковый
конвейер `imagery/` отдельным процессом (своё окружение `imagery/.venv` с rasterio) и сохраняет его
результат в `imagery_results`, `imagery_warnings`, `imagery_skipped`; каждый запуск записывается в
`imagery_runs`. Эндпоинты `/parcels`, `/parcels/{id}/imagery?date=`, `/parcels/{id}/imagery/history`,
`/imagery/refresh`, `/imagery/status`, `/imagery/import` и PNG в `/overlays/` описаны в корневом `README.md`.

| Переменная | По умолчанию | |
|---|---|---|
| `IMAGERY_RUN_AT` | `21:00` | время ежедневного запуска (Кишинёв, летнее время) |
| `IMAGERY_AUTO` | `1` | `0`: только ручной запуск через `POST /imagery/refresh` |
| `IMAGERY_SEASON_START` | `1 мая текущего года` | с какого дня брать снимки |

## Логика заморозка

`app/frost.py`: уровень берётся из sensors-alerts, API добавляет приоритет (WARNING → medium,
CRITICAL → high), рекомендацию и причины: ниже/около нуля, остывание за последний час, иней или
«чёрный» заморозок (сухой воздух, точка росы далеко ниже температуры).

`data/frost-night-chisinau-2020-04-01.csv` — реальная ночь с заморозком (Кишинёв, 1–2 апреля 2020, до −4°C)
в формате реплея sensors-alerts. Источник: Open-Meteo Historical Weather API (ERA5), CC BY 4.0.
