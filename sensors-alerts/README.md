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

Commands: `/start`, `/parcele`, `/status <parcelId>`.

## Demo steps

```powershell
# 1. Frost on one parcel: WARNING after ~40 s, CRITICAL after ~50 s
Invoke-RestMethod -Method Post http://localhost:8081/demo/frost/6401512.058

# 2. Replay the frost night (14 h in ~2.5 min): WARNING, CRITICAL, then all-clear in the morning
Invoke-RestMethod -Method Post http://localhost:8081/demo/replay/6401204.045

# 3. Humid, warm air (disease risk) / dry, hot air (drought stress): alert after ~50 s
Invoke-RestMethod -Method Post http://localhost:8081/demo/humid/6401307.102
Invoke-RestMethod -Method Post http://localhost:8081/demo/dry/6401512.033

# 4. One parcel back to normal weather: the all-clear messages are sent
Invoke-RestMethod -Method Post http://localhost:8081/demo/normal/6401307.102

# 5. Everything back to normal, alerts and cooldowns cleared (no all-clear messages)
Invoke-RestMethod -Method Post http://localhost:8081/demo/reset
```

FROST, HUMID and DRY go past the thresholds of the parcel's crop, so the alert fires whatever the crop.

Always call `/demo/reset` between demo runs; otherwise the cooldown (30 min by default) hides
a repeated alert. For rehearsals set `FROST_COOLDOWN_SECONDS=30`.

### Demo file

`demo/frost-demo.csv` is a made-up night that falls fast, freezes down to -4.3 °C and recovers in the
morning. `demo/demo.ps1` replays it on one parcel and prints every reading and every message.

```powershell
# window 1, from sensors-alerts/
$env:REPLAY_FILE = "file:demo/frost-demo.csv"
mvn spring-boot:run

# window 2, from sensors-alerts/ (takes about 2 minutes)
powershell -ExecutionPolicy Bypass -File demo\demo.ps1
```

`-ParcelId 6401204.045` picks another parcel.

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/sensors/parcels` | the parcels this service has sensors for: `id, name, crop` |
| PUT | `/sensors/parcels/{id}` | body `{"name": ..., "crop": ...}`: adds the parcel (it gets a sensor) or updates its name and crop. The backend calls this for its parcels |
| GET | `/sensors/parcels/{id}/latest` | `parcelId, timestamp, temperatureC, humidityPct, dewPointC, frostLevel, crop, humidityLevel, mode` |
| GET | `/sensors/parcels/{id}/readings?minutes=60` | list of `parcelId, timestamp, temperatureC, humidityPct` |
| GET | `/alerts?parcelId={id}&type=FROST` | newest first: `parcelId, parcelName, crop, type, level, temperatureC, humidityPct, dewPointC, timestamp, message` |
| POST | `/demo/frost/{parcelId}` | switches the parcel to FROST |
| POST | `/demo/humid/{parcelId}` | switches the parcel to HUMID (warm and humid) |
| POST | `/demo/dry/{parcelId}` | switches the parcel to DRY (hot and dry) |
| POST | `/demo/replay/{parcelId}` | starts the CSV replay |
| POST | `/demo/normal/{parcelId}` | one parcel back to NORMAL; all-clear messages are sent |
| POST | `/demo/reset` | all parcels NORMAL, alerts and cooldowns cleared |

`frostLevel` / `level` is `OK`, `WARNING` or `CRITICAL`. An alert with level `OK` is the all-clear.
`humidityLevel` is `OK`, `LOW` or `HIGH`. `crop` is the crop key of the parcel, e.g. `wheat`.
`/alerts` without `parcelId` returns all parcels.

Alert `type` is `FROST`, `HUMIDITY_HIGH` or `HUMIDITY_LOW`; humidity alerts have level `WARNING`
(or `OK` for the all-clear). **`/alerts` returns only frost alerts unless asked otherwise**, because
existing clients title every alert as a frost alert: use `type=HUMIDITY` or `type=ALL` for the rest.

During REPLAY the reading timestamps are those of the recorded night, and `minutes` is counted
back from the newest reading. Switching into or out of REPLAY clears that parcel's readings.

## Configuration (`src/main/resources/application.yml`)

- `app.parcels` – the parcels known at start-up. The backend registers its own parcels at runtime
  (`PUT /sensors/parcels/{id}`), which are kept in memory until the next restart.
- `app.crops` – per-crop thresholds and advice texts (see below).
- `app.simulator` – reading interval, ramp time of the demo modes, replay file and speed.
- `app.frost` – falling-fast rule, all-clear margin and cooldown. The rule is `ThresholdFrostRule` behind `FrostRule`.
- `app.humidity` – minimum temperature for disease risk and all-clear margin. The rule is `ThresholdHumidityRule` behind `HumidityRule`.
- `app.cors-origins` / `FRONTEND_ORIGIN` – allowed frontend origins, `*` by default.

### Crops

Each parcel has a crop, and each crop has its own thresholds. The crop keys are the same as in the backend.

| Crop | Frost warning | Frost critical | Humidity low | Humidity high |
|---|---|---|---|---|
| `wheat` (grâu) | 0 °C | -3 °C | 30% | 85% |
| `barley` (orz) | 0 °C | -3 °C | 30% | 85% |
| `corn` (porumb) | 3 °C | 0 °C | 35% | 85% |
| `sunflower` (floarea-soarelui) | 1 °C | -3 °C | 25% | 80% |
| `orchard` (livadă) | 2 °C | -1 °C | 35% | 85% |
| `vineyard` (viță-de-vie) | 2 °C | -1 °C | 30% | 80% |

**These numbers are starting points for spring conditions, not verified agronomy**; the research
teammate should check them. They are plain values in `application.yml`, as are the advice texts.
A parcel with no crop, or a crop not listed, uses 2 °C / 0 °C and 30% / 85%.

- Frost uses air temperature: WARNING at or below the crop's warning threshold (or when falling
  fast towards it), CRITICAL at or below its critical threshold.
- High humidity means fungal disease risk, and only counts at 10 °C or warmer, so a humid frost
  night does not also raise a disease alert. Low humidity means drought stress.

### Replay CSV

`timestamp,temperatureC,humidityPct`, one row per line, comma or semicolon separated. Timestamps
like `2025-04-08T18:00` or `2025-04-08 18:00:00` are read as Chișinău local time; an offset or `Z`
is also accepted. The bundled `replay/sample-frost-night.csv` is **made-up sample data**. To use the
real night, point `REPLAY_FILE` at it, e.g. `$env:REPLAY_FILE = "file:C:/data/frost-night.csv"`.
The file is re-read on every replay start, so it can be swapped without a restart.

## Alert behaviour

- A frost episode runs from the first alert until the temperature is more than 1 °C above the
  crop's warning threshold.
- A humidity episode runs from the alert until humidity is 5 points back inside the crop's range.
  It sends one message, and the same cooldown applies.
- Each level is sent once per episode. WARNING → CRITICAL is always sent.
- A new episode's alert is suppressed if the same level was sent for that parcel within the cooldown.
- The all-clear is sent only if an alert was actually sent in that episode.
- A failed Telegram send is logged and retried once.

## Tests

`mvn test` – unit tests for the frost and humidity rules.
