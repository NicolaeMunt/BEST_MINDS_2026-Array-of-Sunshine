# sensors-alerts

Sensor simulator, frost rule and Telegram bot (Coder 2). One Spring Boot app, no database, no broker.

## Run

Needs JDK 21+ and Maven.

```powershell
$env:TELEGRAM_BOT_TOKEN    = "123456:ABC..."   # from @BotFather
$env:TELEGRAM_BOT_USERNAME = "my_frost_bot"
$env:TELEGRAM_CHAT_ID      = "111222333"       # optional: demo phone, always gets alerts
mvn spring-boot:run
```

The app listens on port 8081 (`PORT` to change). Without a token it still runs and writes the
alert texts to the log instead of sending them.

Docker: `docker build -t sensors-alerts .` then
`docker run -p 8081:8081 -e TELEGRAM_BOT_TOKEN=... -e TELEGRAM_BOT_USERNAME=... sensors-alerts`

## Telegram bot token

1. In Telegram open **@BotFather**, send `/newbot`, pick a name and a username ending in `bot`.
2. Copy the token into `TELEGRAM_BOT_TOKEN` and the username into `TELEGRAM_BOT_USERNAME`.
3. Start the app, open your bot and send `/start`. The reply ends with `Chat ID: ...`;
   put that into `TELEGRAM_CHAT_ID` so the phone gets alerts even after a restart
   (subscriptions from `/start` are kept in memory only).

Commands: `/start`, `/parcele`, `/status <parcelId>`.

## Demo steps

```powershell
# 1. Frost on one parcel: WARNING after ~40 s, CRITICAL after ~50 s
Invoke-RestMethod -Method Post http://localhost:8081/demo/frost/P1

# 2. Replay the frost night (14 h in ~2.5 min): WARNING, CRITICAL, then all-clear in the morning
Invoke-RestMethod -Method Post http://localhost:8081/demo/replay/P2

# 3. Back to normal, alerts and cooldowns cleared
Invoke-RestMethod -Method Post http://localhost:8081/demo/reset
```

Always call `/demo/reset` between demo runs; otherwise the cooldown (30 min by default) hides
a repeated alert. For rehearsals set `FROST_COOLDOWN_SECONDS=30`.

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/sensors/parcels/{id}/latest` | `parcelId, timestamp, temperatureC, humidityPct, dewPointC, frostLevel` |
| GET | `/sensors/parcels/{id}/readings?minutes=60` | list of `parcelId, timestamp, temperatureC, humidityPct` |
| GET | `/alerts?parcelId={id}` | newest first: `parcelId, parcelName, level, temperatureC, humidityPct, dewPointC, timestamp, message` |
| POST | `/demo/frost/{parcelId}` | switches the parcel to FROST |
| POST | `/demo/replay/{parcelId}` | starts the CSV replay |
| POST | `/demo/reset` | all parcels NORMAL, alerts and cooldowns cleared |

`frostLevel` / `level` is `OK`, `WARNING` or `CRITICAL`. An alert with level `OK` is the all-clear.
`/alerts` without `parcelId` returns all parcels.

During REPLAY the reading timestamps are those of the recorded night, and `minutes` is counted
back from the newest reading. Switching into or out of REPLAY clears that parcel's readings.

## Configuration (`src/main/resources/application.yml`)

- `app.parcels` – IDs and names; **must match Coder 3's IDs**.
- `app.simulator` – reading interval, frost ramp time, replay file and speed.
- `app.frost` – thresholds and cooldown. The rule itself is `ThresholdFrostRule` behind `FrostRule`.
- `app.cors-origins` / `FRONTEND_ORIGIN` – allowed frontend origins, `*` by default.

### Replay CSV

`timestamp,temperatureC,humidityPct`, one row per line, comma or semicolon separated. Timestamps
like `2025-04-08T18:00` or `2025-04-08 18:00:00` are read as Chișinău local time; an offset or `Z`
is also accepted. The bundled `replay/sample-frost-night.csv` is **made-up sample data**. To use the
real night, point `REPLAY_FILE` at it, e.g. `$env:REPLAY_FILE = "file:C:/data/frost-night.csv"`.
The file is re-read on every replay start, so it can be swapped without a restart.

## Alert behaviour

- A frost episode runs from the first alert until the temperature is back above 3 °C.
- Each level is sent once per episode. WARNING → CRITICAL is always sent.
- A new episode's alert is suppressed if the same level was sent for that parcel within the cooldown.
- The all-clear is sent only if an alert was actually sent in that episode.
- A failed Telegram send is logged and retried once.

## Tests

`mvn test` – unit tests for the frost rule.
