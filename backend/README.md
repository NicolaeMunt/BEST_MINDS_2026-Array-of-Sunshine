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
   $env:REPLAY_FILE = "file:../backend/data/frost-night-orhei-2025-04-09.csv"
   $env:FROST_COOLDOWN_SECONDS = "30"    # для репетиций
   mvn spring-boot:run                   # или: java -jar target/sensors-alerts-0.1.0.jar
   ```
2. API:
   ```bash
   cd backend
   pip install -r requirements.txt       # PyYAML: правила культур читаются из application.yml sensors-alerts
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

Чтобы было что показать, в `data/` лежит сезон для пяти демо-участков **по реальной погоде 2026 года**:
Open-Meteo Historical Weather API (реанализ ERA5, CC BY 4.0) в центре каждого участка. Это не измерения
датчика в поле, но тот же сезон, что видел спутник: дождливая первая неделя июня, жаркий и сухой август.

| | |
|---|---|
| `data/sensor-history-sample.csv` | показания раз в час с 1 апреля: `parcelId,timestamp,temperatureC,humidityPct,precipitationMm,soilTemperatureC,soilMoisturePct` (почва: ERA5-Land, температура 0–7 см, влажность 7–28 см) |
| `data/alert-history-sample.csv` | оповещения, которые эти показания вызвали бы по правилам культур (70 за сезон) |
| `python load_sample.py` | загружает оба файла в базу (можно запускать повторно); `start.ps1` делает это для новой базы |
| `python make_sample.py` | скачивает погоду до вчерашнего дня (нужен интернет) и пересоздаёт файлы, эпизоды для демо HUMID/DRY (`sensors-alerts/src/main/resources/replay/`) и ночь заморозка |

Правила культур (фазы, пороги заморозка, болезни, сухой воздух, параметры воды) читаются из `app.crops` в
`sensors-alerts/src/main/resources/application.yml` (`app/crops.py`), поэтому история считается теми же
правилами, что и живые оповещения. Если база создана со старым придуманным сезоном, удалите
`backend/sensors.db`: `start.ps1` создаст её заново с новым.

## Полив и посев

Если у участка есть датчик почвы (данные за последние два дня), решение о поливе принимается по влажности почвы:
культура страдает, когда влажность ниже `ПВ − p × (ПВ − ВЗ)` (FAO-56, пылеватый суглинок: ПВ 27%, ВЗ 10%).
Полив виден сам: влажность растёт больше чем на 3 пункта за 6 часов без дождя за последние 48 часов.
Без датчика почвы — водный баланс ниже. `app/sowing.py`: «можно сеять», когда средняя за день температура почвы на
5 см держится не ниже 10 °C три дня подряд в окне сева культуры (кукуруза, подсолнечник; `sowing` в
`application.yml`). Оповещения `IRRIGATION` и `SOWING` вычисляются, показываются в `GET /alerts` и раз в час
(и сразу при скачке влажности почвы) уходят в Telegram через sensors-alerts (`POST /sensors/parcels/{id}/advice`).

## Водный баланс (без датчика почвы)

`app/water.py` считает водный баланс почвы каждого участка по методу FAO-56 из сохранённых показаний:
ET0 по Hargreaves из минимальной и максимальной температуры дня, коэффициент культуры Kc фазы, дождь
возвращает воду. Когда дефицит превышает легкодоступную воду (RAW = p × TAW), пора поливать.
Предполагается неорошаемое поле с полной почвой на 1 мая. Оповещения `IRRIGATION` (день, когда дефицит
перешёл порог, и день, когда дождь вернул воду) вычисляются из баланса и отдаются в `GET /alerts`
вместе с остальными. Раз в час (`ADVICE_CHECK_SEC`, по умолчанию 3600; сразу при старте и при скачке влажности почвы)
коллектор передаёт новые оповещения за сегодня и вчера в sensors-alerts, который отправляет их в Telegram;
затем они хранятся в `sensor_alerts` и повторно не отправляются.

## Эндпоинты

| | |
|---|---|
| `GET /sensors/parcels` | датчики (`id`, `name`, `crop`) с последним показанием в `latest` (`null`, пока показаний нет) и водой в почве сегодня в `water` |
| `GET /sensors/parcels/{id}/latest` | контракт sensors-alerts + `mode`, `dropLastHourC`, `frost` (приоритет, рекомендация, причины) |
| `GET /sensors/parcels/{id}/readings?minutes=60` | сохранённые показания из базы + `dewPointC`. До 2 часов — сами показания (не больше 300, равномерно прорежены); дольше — по точке на 5 минут, час или день со средним и `minTemperatureC` / `maxTemperatureC` |
| `GET /sensors/parcels/{id}/water?date=` | вода на дату: источник (`sensor` / `balance`), влажность почвы и порог, нужно ли поливать (`irrigate`) и сколько минимум (`amountMm`), замеченные поливы, плюс баланс по дням с 1 мая |
| `GET /alerts?parcelId={id}&type=ALL` | оповещения, новые первыми: сохранённые + `IRRIGATION` из баланса; контракт + `priority`, `title`; уровень `OK` — отбой тревоги. `type`: `FROST`, `HUMIDITY`, `IRRIGATION`, `SOWING`, `ALL` |
| `POST /demo/{frost\|humid\|dry\|replay\|normal\|irrigate}/{parcelId}` | → sensors-alerts: режим симулятора, `irrigate` — полив (влажность почвы растёт без дождя); `409` с причиной |
| `POST /demo/reset` | → sensors-alerts: всё в NORMAL, оповещения и cooldowns очищены |

Если sensors-alerts не отвечает, эндпоинты `/sensors/parcels`, `latest` и `/demo` возвращают `503`;
`readings` и `/alerts` продолжают отдавать то, что уже сохранено.

`GET /sensors/parcels/6401512.058/latest`:
```jsonc
{ "parcelId": "6401512.058", "timestamp": "2026-10-03T14:24:41.6Z", "temperatureC": -2.8, "humidityPct": 57,
  "dewPointC": -10.1, "frostLevel": "CRITICAL",          // OK | WARNING | CRITICAL (из sensors-alerts)
  "crop": "orchard", "humidityLevel": "OK",              // OK | HIGH (риск болезни) | LOW (сухой горячий воздух)
  "phase": "coacere și recoltare", "frostWarningC": 0.0, "frostCriticalC": -2.0,  // фаза культуры и её пороги
  "disease": null,                                        // болезнь, за которой следят в этот день
  "mode": "REPLAY",                                       // NORMAL | FROST | HUMID | DRY | REPLAY
  "dropLastHourC": 1.2,                                   // на сколько холоднее, чем час назад
  "frost": { "frostLevel": "CRITICAL", "score": 95, "priority": "high", "title": "Îngheț",
             "message": "Pornește imediat protecția ...",
             "reasons": [{ "code": "black_frost", "text": "Aer uscat (punct de rouă -10.1°C) — ...", "source": "sensor" }] } }
```

## Участки и спутник

Участки (кадастровый номер, название, культура, полигон) берутся из `data/parcels.geojson` и при старте
записываются в базу (`users`, `parcels`). Если в базе ещё нет результатов спутника, при старте загружается последний
сохранённый `imagery/out/imagery.json`, чтобы карта работала и без интернета. Модуль `app/imagery.py` раз в день запускает спутниковый
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

`data/frost-night-orhei-2025-04-09.csv` — реальная ночь с заморозком у сада под Оргеевом (8–9 апреля 2025,
до −3,2 °C, яблони в фазе бутонов), в формате реплея sensors-alerts; её использует `start.ps1`.
`data/frost-night-chisinau-2020-04-01.csv` — прежняя ночь (Кишинёв, 1–2 апреля 2020, до −4 °C): по календарю
культур она приходится до чувствительных фаз. Источник обеих: Open-Meteo Historical Weather API (ERA5), CC BY 4.0.
