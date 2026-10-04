package md.agro.sensors.alert;

import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.config.CropCalendar;
import md.agro.sensors.frost.FrostAssessment;
import md.agro.sensors.frost.FrostLevel;
import md.agro.sensors.frost.FrostRule;
import md.agro.sensors.humidity.HumidityAssessment;
import md.agro.sensors.humidity.HumidityRule;
import md.agro.sensors.model.Alert;
import md.agro.sensors.model.AlertType;
import md.agro.sensors.model.Reading;
import md.agro.sensors.store.ParcelRegistry;
import md.agro.sensors.store.SensorStore;

/** Runs the frost and humidity rules on every reading and decides what gets sent. */
@Service
public class AlertService {

    private static final Logger log = LoggerFactory.getLogger(AlertService.class);

    /** One frost episode per parcel: from the first alert level until the all-clear. */
    private static final class Episode {
        FrostLevel level = FrostLevel.OK;
        boolean notified;
    }

    /** One humidity episode per parcel: from the first HIGH (or LOW) until the rule no longer says so. */
    private static final class HumidityEpisode {
        final AlertType type;
        boolean notified;

        HumidityEpisode(AlertType type) {
            this.type = type;
        }
    }

    private final AppProperties props;
    private final ParcelRegistry parcels;
    private final FrostRule frostRule;
    private final HumidityRule humidityRule;
    private final SensorStore store;
    private final AlertNotifier notifier;

    private final Map<String, Episode> episodes = new HashMap<>();
    private final Map<String, HumidityEpisode> humidityEpisodes = new HashMap<>();
    private final Map<String, Instant> lastSent = new HashMap<>();

    public AlertService(AppProperties props, ParcelRegistry parcels, FrostRule frostRule, HumidityRule humidityRule, SensorStore store,
            AlertNotifier notifier) {
        this.props = props;
        this.parcels = parcels;
        this.frostRule = frostRule;
        this.humidityRule = humidityRule;
        this.store = store;
        this.notifier = notifier;
    }

    public synchronized void onReading(Reading reading) {
        AppProperties.Crop crop = parcels.cropFor(reading.parcelId());
        List<Reading> history = store.readings(reading.parcelId());
        FrostAssessment a = frostRule.evaluate(reading, history, crop);
        HumidityAssessment humidity = humidityRule.evaluate(reading, history, crop);
        store.addReading(reading, a, humidity.level());
        log.info("{} {} {} °C {}% dew {} °C -> frost {}, humidity {}", reading.parcelId(), reading.timestamp(),
                Messages.num(reading.temperatureC()), Messages.num(reading.humidityPct()),
                Messages.num(a.dewPointC()), a.level(), humidity.level());

        checkFrost(reading, a, crop);
        checkHumidity(reading, a, humidity, crop);
    }

    private void checkFrost(Reading reading, FrostAssessment a, AppProperties.Crop crop) {
        Episode ep = episodes.computeIfAbsent(reading.parcelId(), k -> new Episode());
        FrostLevel level = a.level();
        String name = parcelName(reading);
        AppProperties.Phase phase = CropCalendar.phase(crop, reading.timestamp());

        if (level.compareTo(ep.level) > 0) {
            // Each level is sent at most once per episode, so noise around a threshold cannot spam.
            boolean escalation = ep.level == FrostLevel.WARNING && level == FrostLevel.CRITICAL;
            ep.level = level;
            String key = key(reading.parcelId(), "FROST_" + level);
            if (escalation || !inCooldown(key)) {
                send(reading, a, AlertType.FROST, level, Messages.frost(name, crop, phase, reading, a));
                ep.notified = true;
                lastSent.put(key, Instant.now());
            } else {
                log.info("{} frost {} suppressed by cooldown", reading.parcelId(), level);
            }
        } else if (level == FrostLevel.OK && ep.level != FrostLevel.OK
                && (!phase.frostHarms() || reading.temperatureC() > phase.frostWarningC() + props.frost().allClearMarginC())) {
            if (ep.notified) {
                send(reading, a, AlertType.FROST, FrostLevel.OK, Messages.frostAllClear(name, crop, reading));
            }
            episodes.remove(reading.parcelId());
        }
    }

    private void checkHumidity(Reading reading, FrostAssessment a, HumidityAssessment h, AppProperties.Crop crop) {
        HumidityEpisode ep = humidityEpisodes.get(reading.parcelId());
        String name = parcelName(reading);
        AlertType type = switch (h.level()) {
            case HIGH -> AlertType.HUMIDITY_HIGH;
            case LOW -> AlertType.HUMIDITY_LOW;
            case OK -> null;
        };

        // The rule counts hours over a window, so it does not flicker around a threshold: OK ends the episode.
        if (ep != null && ep.type != type) {
            if (ep.notified) {
                send(reading, a, ep.type, FrostLevel.OK, Messages.humidityAllClear(name, crop, reading, ep.type));
            }
            humidityEpisodes.remove(reading.parcelId());
            ep = null;
        }
        if (ep == null && type != null) {
            ep = new HumidityEpisode(type);
            humidityEpisodes.put(reading.parcelId(), ep);
            String key = key(reading.parcelId(), type.name());
            if (!inCooldown(key)) {
                send(reading, a, type, FrostLevel.WARNING, Messages.humidity(name, crop, reading, h));
                ep.notified = true;
                lastSent.put(key, Instant.now());
            } else {
                log.info("{} {} suppressed by cooldown", reading.parcelId(), type);
            }
        }
    }

    /** Clears alerts, episodes and cooldowns. */
    public synchronized void reset() {
        episodes.clear();
        humidityEpisodes.clear();
        lastSent.clear();
        store.clearAlerts();
    }

    private boolean inCooldown(String key) {
        Instant last = lastSent.get(key);
        return last != null
                && Duration.between(last, Instant.now()).getSeconds() < props.frost().cooldownSeconds();
    }

    private void send(Reading r, FrostAssessment a, AlertType type, FrostLevel level, String text) {
        Alert alert = new Alert(r.parcelId(), parcelName(r), parcels.cropKey(r.parcelId()), type, level,
                r.temperatureC(), r.humidityPct(), round1(a.dewPointC()), Instant.now(), text);
        store.addAlert(alert);
        try {
            notifier.send(alert);
        } catch (RuntimeException e) {
            log.error("Notifier failed for {}", r.parcelId(), e);
        }
    }

    private String parcelName(Reading r) {
        return parcels.name(r.parcelId());
    }

    private static String key(String parcelId, String what) {
        return parcelId + "|" + what;
    }

    private static double round1(double v) {
        return Math.round(v * 10) / 10.0;
    }
}
