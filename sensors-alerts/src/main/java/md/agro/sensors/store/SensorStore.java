package md.agro.sensors.store;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.frost.FrostAssessment;
import md.agro.sensors.model.Alert;
import md.agro.sensors.model.Reading;
import org.springframework.stereotype.Component;

/** In-memory state: bounded readings and alerts per parcel. */
@Component
public class SensorStore {

    private static final int MAX_ALERTS_PER_PARCEL = 50;

    public record Status(Reading reading, FrostAssessment assessment) {
    }

    private final int maxReadings;
    private final Map<String, Deque<Reading>> readings = new ConcurrentHashMap<>();
    private final Map<String, Deque<Alert>> alerts = new ConcurrentHashMap<>();
    private final Map<String, Status> latest = new ConcurrentHashMap<>();

    public SensorStore(AppProperties props) {
        this.maxReadings = props.simulator().maxReadingsPerParcel();
    }

    public void addReading(Reading reading, FrostAssessment assessment) {
        Deque<Reading> q = readings.computeIfAbsent(reading.parcelId(), k -> new ArrayDeque<>());
        synchronized (q) {
            q.addLast(reading);
            while (q.size() > maxReadings) {
                q.removeFirst();
            }
        }
        latest.put(reading.parcelId(), new Status(reading, assessment));
    }

    /** All stored readings of a parcel, oldest first. */
    public List<Reading> readings(String parcelId) {
        Deque<Reading> q = readings.get(parcelId);
        if (q == null) {
            return List.of();
        }
        synchronized (q) {
            return new ArrayList<>(q);
        }
    }

    /** Readings of the last N minutes, counted back from the newest reading (replay time is in the past). */
    public List<Reading> readings(String parcelId, int minutes) {
        List<Reading> all = readings(parcelId);
        if (all.isEmpty()) {
            return all;
        }
        Instant from = all.get(all.size() - 1).timestamp().minus(Duration.ofMinutes(minutes));
        return all.stream().filter(r -> !r.timestamp().isBefore(from)).toList();
    }

    public void clearReadings(String parcelId) {
        Deque<Reading> q = readings.get(parcelId);
        if (q != null) {
            synchronized (q) {
                q.clear();
            }
        }
    }

    public Optional<Status> latest(String parcelId) {
        return Optional.ofNullable(latest.get(parcelId));
    }

    public void addAlert(Alert alert) {
        Deque<Alert> q = alerts.computeIfAbsent(alert.parcelId(), k -> new ArrayDeque<>());
        synchronized (q) {
            q.addFirst(alert);
            while (q.size() > MAX_ALERTS_PER_PARCEL) {
                q.removeLast();
            }
        }
    }

    /** Newest first. */
    public List<Alert> alerts(String parcelId) {
        Deque<Alert> q = alerts.get(parcelId);
        if (q == null) {
            return List.of();
        }
        synchronized (q) {
            return new ArrayList<>(q);
        }
    }

    /** All parcels, newest first. */
    public List<Alert> alerts() {
        return alerts.keySet().stream()
                .flatMap(id -> alerts(id).stream())
                .sorted(Comparator.comparing(Alert::timestamp).reversed())
                .toList();
    }

    public void clearAlerts() {
        alerts.clear();
    }
}
