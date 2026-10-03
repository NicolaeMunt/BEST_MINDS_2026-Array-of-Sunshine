package md.agro.sensors.alert;

import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.frost.FrostAssessment;
import md.agro.sensors.frost.FrostLevel;
import md.agro.sensors.frost.FrostRule;
import md.agro.sensors.model.Alert;
import md.agro.sensors.model.Reading;
import md.agro.sensors.store.SensorStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/** Runs the frost rule on every reading and decides what gets sent. */
@Service
public class AlertService {

    private static final Logger log = LoggerFactory.getLogger(AlertService.class);

    /** One frost episode per parcel: from the first alert level until the all-clear. */
    private static final class Episode {
        FrostLevel level = FrostLevel.OK;
        boolean notified;
    }

    private final AppProperties props;
    private final FrostRule rule;
    private final SensorStore store;
    private final AlertNotifier notifier;

    private final Map<String, Episode> episodes = new HashMap<>();
    private final Map<String, Instant> lastSent = new HashMap<>();

    public AlertService(AppProperties props, FrostRule rule, SensorStore store, AlertNotifier notifier) {
        this.props = props;
        this.rule = rule;
        this.store = store;
        this.notifier = notifier;
    }

    public synchronized void onReading(Reading reading) {
        List<Reading> history = store.readings(reading.parcelId());
        FrostAssessment a = rule.evaluate(reading, history);
        store.addReading(reading, a);
        log.info("{} {} {} °C {}% dew {} °C -> {}", reading.parcelId(), reading.timestamp(),
                Messages.num(reading.temperatureC()), Messages.num(reading.humidityPct()),
                Messages.num(a.dewPointC()), a.level());

        Episode ep = episodes.computeIfAbsent(reading.parcelId(), k -> new Episode());
        FrostLevel level = a.level();

        if (level.compareTo(ep.level) > 0) {
            // Each level is sent at most once per episode, so noise around a threshold cannot spam.
            boolean escalation = ep.level == FrostLevel.WARNING && level == FrostLevel.CRITICAL;
            ep.level = level;
            if (escalation || !inCooldown(reading.parcelId(), level)) {
                send(reading, a, level);
                ep.notified = true;
                lastSent.put(key(reading.parcelId(), level), Instant.now());
            } else {
                log.info("{} {} suppressed by cooldown", reading.parcelId(), level);
            }
        } else if (level == FrostLevel.OK && ep.level != FrostLevel.OK
                && reading.temperatureC() > props.frost().allClearTempC()) {
            if (ep.notified) {
                send(reading, a, FrostLevel.OK);
            }
            episodes.remove(reading.parcelId());
        }
    }

    /** Clears alerts, episodes and cooldowns. */
    public synchronized void reset() {
        episodes.clear();
        lastSent.clear();
        store.clearAlerts();
    }

    private boolean inCooldown(String parcelId, FrostLevel level) {
        Instant last = lastSent.get(key(parcelId, level));
        return last != null
                && Duration.between(last, Instant.now()).getSeconds() < props.frost().cooldownSeconds();
    }

    private void send(Reading r, FrostAssessment a, FrostLevel level) {
        String name = props.parcel(r.parcelId()).map(AppProperties.Parcel::name).orElse(r.parcelId());
        String text = level == FrostLevel.OK ? Messages.allClear(name, r) : Messages.alert(name, r, a);
        Alert alert = new Alert(r.parcelId(), name, level, r.temperatureC(), r.humidityPct(),
                round1(a.dewPointC()), Instant.now(), text);
        store.addAlert(alert);
        try {
            notifier.send(alert);
        } catch (RuntimeException e) {
            log.error("Notifier failed for {}", r.parcelId(), e);
        }
    }

    private static String key(String parcelId, FrostLevel level) {
        return parcelId + "|" + level;
    }

    private static double round1(double v) {
        return Math.round(v * 10) / 10.0;
    }
}
