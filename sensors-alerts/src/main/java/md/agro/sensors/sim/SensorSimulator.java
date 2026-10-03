package md.agro.sensors.sim;

import java.io.IOException;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;

import jakarta.annotation.PreDestroy;
import md.agro.sensors.alert.AlertService;
import md.agro.sensors.config.AppProperties;
import md.agro.sensors.model.Reading;
import md.agro.sensors.model.SensorMode;
import md.agro.sensors.store.ParcelRegistry;
import md.agro.sensors.store.SensorStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Service;

/** One virtual sensor per parcel. Readings go straight into {@link AlertService}. */
@Service
public class SensorSimulator {

    private static final Logger log = LoggerFactory.getLogger(SensorSimulator.class);
    private static final ZoneId ZONE = ZoneId.of("Europe/Chisinau");

    private static final class Sensor {
        final String parcelId;
        SensorMode mode = SensorMode.NORMAL;
        // Bumped on every mode switch; ticks scheduled for an older generation stop themselves.
        int generation;
        double lastTemp = Double.NaN;
        double lastHum = Double.NaN;

        // FROST, HUMID and DRY move linearly from the values at the switch to a target.
        Instant rampStart;
        double rampFromTemp;
        double rampFromHum;
        double rampToTemp;
        double rampToHum;

        List<ReplayData.Row> replay = List.of();
        int replayIndex;

        Sensor(String parcelId) {
            this.parcelId = parcelId;
        }
    }

    private final ParcelRegistry parcels;
    private final AppProperties.Simulator cfg;
    private final AlertService alertService;
    private final SensorStore store;
    private final ResourceLoader resourceLoader;
    // Guarded by itself; parcels can be added while the simulator runs.
    private final Map<String, Sensor> sensors = new LinkedHashMap<>();
    private boolean started;
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2);

    public SensorSimulator(AppProperties props, ParcelRegistry parcels, AlertService alertService, SensorStore store,
            ResourceLoader resourceLoader) {
        this.parcels = parcels;
        this.cfg = props.simulator();
        this.alertService = alertService;
        this.store = store;
        this.resourceLoader = resourceLoader;
        parcels.all().forEach(p -> sensors.put(p.id(), new Sensor(p.id())));
    }

    @EventListener(ApplicationReadyEvent.class)
    public void start() {
        synchronized (sensors) {
            started = true;
            log.info("Simulator started for parcels {} every {} s", sensors.keySet(), cfg.intervalSeconds());
            sensors.values().forEach(s -> scheduleTick(s, s.generation, 0));
        }
    }

    /** Starts a virtual sensor for a parcel added at runtime; does nothing if it already has one. */
    public void ensureSensor(String parcelId) {
        synchronized (sensors) {
            if (sensors.containsKey(parcelId)) {
                return;
            }
            Sensor s = new Sensor(parcelId);
            sensors.put(parcelId, s);
            if (started) {
                scheduleTick(s, s.generation, 0);
            }
        }
        log.info("Sensor added for parcel {}", parcelId);
    }

    private Sensor sensor(String parcelId) {
        synchronized (sensors) {
            return sensors.get(parcelId);
        }
    }

    @PreDestroy
    public void stop() {
        scheduler.shutdownNow();
    }

    public boolean hasParcel(String parcelId) {
        return sensor(parcelId) != null;
    }

    public SensorMode mode(String parcelId) {
        Sensor s = sensor(parcelId);
        synchronized (s) {
            return s.mode;
        }
    }

    public void setAll(SensorMode mode) {
        List<String> ids;
        synchronized (sensors) {
            ids = List.copyOf(sensors.keySet());
        }
        ids.forEach(id -> setMode(id, mode));
    }

    /** @throws IllegalStateException if REPLAY is requested and the CSV cannot be loaded */
    public void setMode(String parcelId, SensorMode mode) {
        Sensor s = sensor(parcelId);
        if (s == null) {
            throw new IllegalArgumentException("Unknown parcel " + parcelId);
        }
        // Loaded on every start so the CSV can be swapped without a restart.
        List<ReplayData.Row> rows = mode == SensorMode.REPLAY ? loadReplay() : List.of();
        int generation;
        synchronized (s) {
            // Replay readings carry the timestamps of the recorded night; don't mix them with live ones.
            if (mode == SensorMode.REPLAY || s.mode == SensorMode.REPLAY) {
                store.clearReadings(parcelId);
            }
            s.mode = mode;
            generation = ++s.generation;
            if (mode == SensorMode.FROST || mode == SensorMode.HUMID || mode == SensorMode.DRY) {
                ThreadLocalRandom rnd = ThreadLocalRandom.current();
                // Targets go past the thresholds of the parcel's crop, so the alert fires for any crop.
                AppProperties.Crop crop = parcels.cropFor(parcelId);
                s.rampStart = Instant.now();
                s.rampFromTemp = Double.isNaN(s.lastTemp) ? normalTemp() : s.lastTemp;
                s.rampFromHum = Double.isNaN(s.lastHum) ? normalHumidity(s.rampFromTemp) : s.lastHum;
                switch (mode) {
                    case FROST -> {
                        s.rampToTemp = crop.frostCriticalC() - rnd.nextDouble(0.5, 2.0);
                        s.rampToHum = rnd.nextDouble(87, 93);
                    }
                    case HUMID -> {
                        s.rampToTemp = rnd.nextDouble(16, 19);
                        s.rampToHum = Math.min(98, crop.humidityHighPct() + rnd.nextDouble(4, 9));
                    }
                    default -> {
                        s.rampToTemp = rnd.nextDouble(30, 33);
                        s.rampToHum = Math.max(8, crop.humidityLowPct() - rnd.nextDouble(5, 10));
                    }
                }
            } else if (mode == SensorMode.REPLAY) {
                s.replay = rows;
                s.replayIndex = 0;
            }
        }
        log.info("{} -> {}", parcelId, mode);
        scheduleTick(s, generation, 0);
    }

    private void scheduleTick(Sensor s, int generation, long delayMs) {
        scheduler.schedule(() -> tick(s, generation), delayMs, TimeUnit.MILLISECONDS);
    }

    private void tick(Sensor s, int generation) {
        long nextMs = intervalMs();
        try {
            Reading reading;
            synchronized (s) {
                if (s.generation != generation) {
                    return;
                }
                switch (s.mode) {
                    case FROST, HUMID, DRY -> reading = rampReading(s);
                    case REPLAY -> {
                        if (s.replayIndex >= s.replay.size()) {
                            reading = null;
                        } else {
                            ReplayData.Row row = s.replay.get(s.replayIndex++);
                            reading = new Reading(s.parcelId, row.timestamp(), row.temperatureC(),
                                    row.humidityPct());
                            if (s.replayIndex < s.replay.size()) {
                                long gapSec = Duration.between(row.timestamp(),
                                        s.replay.get(s.replayIndex).timestamp()).getSeconds();
                                nextMs = Math.max(50, Math.round(gapSec / 3600.0 * cfg.replaySecondsPerHour() * 1000));
                            }
                        }
                    }
                    default -> reading = normalReading(s);
                }
                if (reading != null) {
                    s.lastTemp = reading.temperatureC();
                    s.lastHum = reading.humidityPct();
                }
            }
            if (reading == null) {
                log.info("{} replay finished", s.parcelId);
                setMode(s.parcelId, SensorMode.NORMAL);
                return;
            }
            alertService.onReading(reading);
        } catch (RuntimeException e) {
            log.error("Tick failed for {}", s.parcelId, e);
        }
        scheduleTick(s, generation, nextMs);
    }

    private Reading normalReading(Sensor s) {
        ThreadLocalRandom rnd = ThreadLocalRandom.current();
        double temp = normalTemp() + rnd.nextDouble(-0.15, 0.15);
        double hum = normalHumidity(temp) + rnd.nextDouble(-1, 1);
        return new Reading(s.parcelId, Instant.now(), round1(temp), round1(clamp(hum, 30, 98)));
    }

    private Reading rampReading(Sensor s) {
        ThreadLocalRandom rnd = ThreadLocalRandom.current();
        double elapsed = Duration.between(s.rampStart, Instant.now()).toMillis() / 1000.0;
        double p = Math.min(1, elapsed / Math.max(1, cfg.frostRampSeconds()));
        double temp = s.rampFromTemp + (s.rampToTemp - s.rampFromTemp) * p + rnd.nextDouble(-0.1, 0.1);
        double hum = s.rampFromHum + (s.rampToHum - s.rampFromHum) * p + rnd.nextDouble(-0.5, 0.5);
        return new Reading(s.parcelId, Instant.now(), round1(temp), round1(clamp(hum, 5, 99)));
    }

    /** Spring day: coldest (6 °C) around 03:00, warmest (18 °C) around 15:00. */
    private static double normalTemp() {
        ZonedDateTime now = ZonedDateTime.now(ZONE);
        double hour = now.getHour() + now.getMinute() / 60.0 + now.getSecond() / 3600.0;
        return 12 + 6 * Math.cos(2 * Math.PI * (hour - 15) / 24);
    }

    private static double normalHumidity(double temp) {
        return 65 - (temp - 12) * 4;
    }

    private List<ReplayData.Row> loadReplay() {
        try {
            List<ReplayData.Row> rows = ReplayData.load(resourceLoader.getResource(cfg.replayFile()), ZONE);
            if (rows.isEmpty()) {
                throw new IllegalStateException("Replay file has no usable rows: " + cfg.replayFile());
            }
            return rows;
        } catch (IOException e) {
            throw new IllegalStateException("Cannot read replay file " + cfg.replayFile(), e);
        }
    }

    private long intervalMs() {
        return Math.max(100, Math.round(cfg.intervalSeconds() * 1000));
    }

    private static double clamp(double v, double min, double max) {
        return Math.max(min, Math.min(max, v));
    }

    private static double round1(double v) {
        return Math.round(v * 10) / 10.0;
    }
}
