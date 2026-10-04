# sensors-alerts

Sensor simulator, per-crop frost and humidity rules, and Telegram bot (Coder 2). One Spring Boot app,
no database, no broker.

## Run

Needs JDK 21+ and Maven.

```powershell
$env:TELEGRAM_BOT_TOKEN    = "123456:ABC..."   # from @BotFather
$env:TELEGRAM_BOT_USERNAME = "my_frost_bot"
$env:TELEGRAM_CHAT_ID      = "111222333"       # optional: demo phone, always gets alerts
mvn spring-boot:run
```

Instead of environment variables you can put the same three values in a `.env` file in this folder
(copy `.env.example`). It is gitignored and read at start-up when the app is run from this folder.

The app listens on port 8081 (`PORT` to change). Without a token it still runs and writes the
alert texts to the log instead of sending them.

Docker: `docker build -t sensors-alerts .` then
`docker run -p 8081:8081 -e TELEGRAM_BOT_TOKEN=... -e TELEGRAM_BOT_USERNAME=... sensors-alerts`

## Telegram bot token

1. In Telegram open **@BotFather**, send `/newbot`, pick a name and a username ending in `bot`.
2. Copy the token into `TELEGRAM_BOT_TOKEN` and the username into `TELEGRAM_BOT_USERNAME`.
3. Start the app, open your bot and send `/start` (in a group: `/start@YourBot`). The chat is
   saved to `telegram-chats.txt` (gitignored) and keeps getting alerts after restarts.
   `TELEGRAM_CHAT_ID` is an optional extra chat that always gets alerts.

Commands: `/start`, `/parcele`, `/status <parcelId>` (the status also shows the crop's phase today).

## Demo steps

The rules depend on the crop's phase on the reading's day (see Crops below), so what fires depends on
the date: in October only the orchard and the vineyard can be hurt by frost, the field crops are ripe
or harvested.

```powershell
# 1. Frost now, on the orchard: WARNING after ~40 s, CRITICAL after ~50 s
Invoke-RestMethod -Method Post http://localhost:8081/demo/frost/6401512.058

# 2. Replay the real frost night of 8-9 April 2025 (start.ps1 sets REPLAY_FILE): on the orchard, in bud,
#    WARNING, CRITICAL at -2.9 °C, then all-clear in the morning
Invoke-RestMethod -Method Post http://localhost:8081/demo/replay/6401512.058

# 3. Replay a real damp spell of 2026 with a disease alert for the crop (wheat: 7 days in ~90 s) or a real
#    hot, dry spell (corn: in ~10 s). A crop without such a spell answers 409 with the reason.
Invoke-RestMethod -Method Post http://localhost:8081/demo/humid/6401307.102
Invoke-RestMethod -Method Post http://localhost:8081/demo/dry/6401512.033

# 4. A watering: the soil moisture rises to field capacity in 30 s, with no rain. After the dry spell above
#    (the soil stays as dry as it was then), the backend says "E timpul să udați" and then sees the watering.
Invoke-RestMethod -Method Post http://localhost:8081/demo/irrigate/6401512.058

# 5. One parcel back to normal weather: the all-clear messages are sent
Invoke-RestMethod -Method Post http://localhost:8081/demo/normal/6401307.102

# 6. Everything back to normal, alerts and cooldowns cleared (no all-clear messages)
Invoke-RestMethod -Method Post http://localhost:8081/demo/reset
```

FROST ramps down past the critical threshold of today's phase; when frost does no harm in today's phase
(not sown, harvested, dormant), nothing fires, as in the field.

HUMID and DRY replay `src/main/resources/replay/{humid|dry}-<crop>.csv`: the first damp spell with a
disease alert and the first hot, dry spell of 2026 at that crop's parcel, from real weather (written by
`backend/make_sample.py`). In 2026 the sunflower had no damp spell in flower (July was dry) and the wheat
no hot, dry day before its harvest, so those two answer 409.

Always call `/demo/reset` between demo runs; otherwise the cooldown (30 min by default) hides
a repeated alert. For rehearsals set `FROST_COOLDOWN_SECONDS=30`.

### Demo file

`demo/frost-demo.csv` is a made-up night that falls fast, freezes down to -4.3 °C and recovers in the
morning (8 April, when the apple trees are in bud). `demo/demo.ps1` replays it on one parcel and prints
every reading and every message.

```powershell
# window 1, from sensors-alerts/
$env:REPLAY_FILE = "file:demo/frost-demo.csv"
mvn spring-boot:run

# window 2, from sensors-alerts/ (takes about 2 minutes)
powershell -ExecutionPolicy Bypass -File demo\demo.ps1
```

`-ParcelId 6401204.045` picks another parcel (the vineyard is still dormant on 8 April: no alert).

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/sensors/parcels` | the parcels this service has sensors for: `id, name, crop` |
| PUT | `/sensors/parcels/{id}` | body `{"name": ..., "crop": ..., "sowingDate": "2026-05-10"}`: adds the parcel (it gets a sensor) or updates its name, crop and sowing date. The backend calls this for its parcels |
| GET | `/sensors/parcels/{id}/latest` | `parcelId, timestamp, temperatureC, humidityPct, precipitationMm, soilTemperatureC, soilMoisturePct, dewPointC, frostLevel, crop, humidityLevel, mode, phase, frostWarningC, frostCriticalC, disease` |
| GET | `/sensors/parcels/{id}/readings?minutes=60` | list of `parcelId, timestamp, temperatureC, humidityPct, precipitationMm, soilTemperatureC, soilMoisturePct` |
| GET | `/alerts?parcelId={id}&type=FROST` | newest first: `parcelId, parcelName, crop, type, level, temperatureC, humidityPct, dewPointC, timestamp, message` |
| POST | `/sensors/parcels/{id}/advice` | body `{"type": "IRRIGATION" or "SOWING", "timestamp", "level", "temperatureC", "humidityPct", "dewPointC", "message"}`: watering or sowing advice from the backend, stored and sent to Telegram like the alerts; the same advice again answers `{"sent": false}` |
| POST | `/demo/irrigate/{parcelId}` | a watering: the live soil moisture rises to field capacity (no rain); 409 while a replay runs |
| POST | `/demo/frost/{parcelId}` | switches the parcel to FROST |
| POST | `/demo/humid/{parcelId}` | HUMID: replays the crop's real damp spell; 409 if it has none |
| POST | `/demo/dry/{parcelId}` | DRY: replays the crop's real hot, dry spell; 409 if it has none |
| POST | `/demo/replay/{parcelId}` | starts the frost night replay |
| POST | `/demo/normal/{parcelId}` | one parcel back to NORMAL; all-clear messages are sent |
| POST | `/demo/reset` | all parcels NORMAL, alerts and cooldowns cleared |

`frostLevel` / `level` is `OK`, `WARNING` or `CRITICAL`. An alert with level `OK` is the all-clear.
`humidityLevel` is `OK`, `HIGH` (disease risk: the air was damp long enough) or `LOW` (dry, hot air).
`crop` is the crop key of the parcel, e.g. `wheat`. `phase` is the crop's phase on the reading's day;
`frostWarningC` / `frostCriticalC` are that phase's thresholds, `null` when frost does no harm then;
`disease` is the disease the damp-air rule watches for that day, `null` outside its window.
`/alerts` without `parcelId` returns all parcels.

Alert `type` is `FROST`, `HUMIDITY_HIGH`, `HUMIDITY_LOW`, or `IRRIGATION` / `SOWING` (advice from the
backend); humidity and advice alerts have level `WARNING` (or `OK` for the all-clear). **`/alerts` returns only
frost alerts unless asked otherwise**, because existing clients title every alert as a frost alert: use
`type=HUMIDITY`, `IRRIGATION`, `SOWING` or `ALL` for the rest.

**The sensor.** Each parcel has one virtual station: air temperature and humidity, rain, and a soil probe with
the soil temperature at ~5 cm (seed depth) and the soil moisture at ~20 cm (% of the soil volume). Live, the
soil temperature follows the air with a lag of 6 hours and the moisture stays where the last replay left it (23%
at start-up) until a watering raises it; replays carry the recorded soil.

During a replay the reading timestamps are those of the recording, and `minutes` is counted back from
the newest reading. Switching into or out of a replay clears that parcel's readings.

## Configuration (`src/main/resources/application.yml`)

- `app.parcels` – the parcels known at start-up. The backend registers its own parcels at runtime
  (`PUT /sensors/parcels/{id}`), which are kept in memory until the next restart.
- `app.crops` – the crop calendar and rules (see below). The backend and the satellite job read the same
  section, so every part of the app uses the same phases and thresholds.
- `app.simulator` – reading interval, ramp time of FROST, the frost night file and the damp/dry spell
  files, and their replay speeds.
- `app.frost` – falling-fast rule, all-clear margin and cooldown. The rule is `ThresholdFrostRule` behind `FrostRule`.
- `app.humidity` – what counts as dry, hot air and how long a risk lasts. The rule is `ThresholdHumidityRule`
  behind `HumidityRule`.
- `app.water` – the soil (field capacity and wilting point, FAO-56 silt loam) and what counts as a watering; the
  backend's water advice uses it, this service only for the demo watering.
- `app.cors-origins` / `FRONTEND_ORIGIN` – allowed frontend origins, `*` by default.

### Crops

Each parcel has a crop; each crop goes through **phases on a fixed calendar** for the Orhei area (a phase
starts on its `from` day and lasts until the next one; an early or late year can be 1-2 weeks off). The
numbers come from extension services and FAO; sources and reasons are in `imagery/LOGIC.md`, section
"Reguli pe culturi".

| Crop | Frost (critical threshold by phase) | Disease watched (damp air) | Dry, hot air harms |
|---|---|---|---|
| `wheat` (grâu) | -11 °C tillering, -4 jointing, -2 boot, -1 heading and flowering, -2 grain fill; none after the harvest (15 July) | head blight: 48 damp hours in 7 days at 15-30 °C, 20 May - 15 June | 15 May - 10 July |
| `corn` (porumb) | -2 °C from sowing to ripening; none after physiological maturity (20 September) | northern leaf blight: 6 damp hours in a row at 18-27 °C, 15 June - 31 August | 10 July - 31 August |
| `sunflower` (floarea-soarelui) | -3 °C seedlings, -1 bud and flower, -4 seed fill; none from 25 August | white head rot: 48 damp hours in 3 days below 29 °C, 1-25 July | 1 July - 15 August |
| `orchard` (livadă, apple) | -5 °C bud break, -2.8 bud, -2 flower, young and ripening fruit; none November - mid March | apple scab: 6 damp hours at 16-24 °C ... 28 hours from 4 °C, 1 April - 31 May | June - August |
| `vineyard` (viță-de-vie) | -1 °C young shoots, -2 ripening grapes; none after the harvest (20 October) and while dormant | downy mildew: 4 hours at 95% or more, 13-29 °C, 15 May - 31 August | June - August |

- **Frost** uses air temperature and the thresholds of the crop's phase on the reading's day: WARNING at
  or below the warning threshold (or when falling fast towards it), CRITICAL at or below the critical one.
  A phase may carry its own frost advice (ripening fruit get different advice than flowers).
- **Disease risk** (`HIGH`): inside the disease's window, at least `hours` damp hours (humidity at or above
  `min-humidity-pct`, standing in for wet leaves) among the last `within-hours`, at the condition's
  temperatures. Hours are clock hours of the reading timestamps (hourly means).
- **Dry, hot air** (`LOW`): inside the crop's dry window, humidity at most 30% at 25 °C or more ("suhovei"
  in the glossary of the Moldovan weather service, without the wind, which is not measured).
- Both risks last `hold-hours` (24) after their conditions were last met, so one rainy spell or one heat
  wave is one alert.

A parcel with no crop, or a crop not listed, gets frost alerts at 2 °C / 0 °C all year and nothing else.

**Sowing date.** Corn and sunflower have `calendar-sowing` (the day the calendar assumes: 20 and 10 April). A
parcel registered with a `sowingDate` N days later gets all its phases, its disease window and its dry window N
days later (`CropCalendar.forSowing`); a date more than 60 days off is ignored. Winter wheat's spring development
does not follow its autumn sowing day, so its calendar stays.

### Replay CSV

`timestamp,temperatureC,humidityPct[,precipitationMm,soilTemperatureC,soilMoisturePct]`, one row per line, comma
or semicolon separated;
lines starting with `#` are comments. Timestamps like `2025-04-08T18:00` or `2025-04-08 18:00:00` are read
as Chișinău local time; an offset or `Z` is also accepted. The bundled `replay/sample-frost-night.csv` is
**made-up sample data**; the real frost night is `backend/data/frost-night-orhei-2025-04-09.csv`
(`$env:REPLAY_FILE = "file:../backend/data/frost-night-orhei-2025-04-09.csv"`). The file is re-read on
every replay start, so it can be swapped without a restart.

## Alert behaviour

- A frost episode runs from the first alert until the temperature is more than 1 °C above the
  phase's warning threshold, or until frost does no harm in the phase.
- A humidity episode runs from the alert until the rule no longer says HIGH (or LOW), i.e. 24 hours after
  its conditions were last met. It sends one message, and the same cooldown applies.
- Each level is sent once per episode. WARNING → CRITICAL is always sent.
- A new episode's alert is suppressed if the same level was sent for that parcel within the cooldown.
- The all-clear is sent only if an alert was actually sent in that episode.
- A failed Telegram send is logged and retried once.

## Tests

`mvn test` – unit tests for the frost rule (thresholds by crop and phase, local days, the sowing date) and
the humidity rule (damp hours, conditions, windows, the 24-hour hold, dry air), and a test that the real
`application.yml` binds.
