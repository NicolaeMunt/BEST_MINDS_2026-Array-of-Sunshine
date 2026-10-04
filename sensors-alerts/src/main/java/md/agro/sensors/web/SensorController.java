package md.agro.sensors.web;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import md.agro.sensors.alert.AlertService;
import md.agro.sensors.config.AppProperties;
import md.agro.sensors.config.CropCalendar;
import md.agro.sensors.frost.FrostLevel;
import md.agro.sensors.humidity.HumidityLevel;
import md.agro.sensors.model.Alert;
import md.agro.sensors.model.AlertType;
import md.agro.sensors.model.Reading;
import md.agro.sensors.model.SensorMode;
import md.agro.sensors.sim.SensorSimulator;
import md.agro.sensors.store.ParcelRegistry;
import md.agro.sensors.store.SensorStore;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class SensorController {

    // Field names here are what Coder 3 sees; align with the shared JSON contract.
    /**
     * @param phase          the crop's phase on the reading's day
     * @param frostWarningC  frost thresholds of that phase; null when frost does no harm in it
     * @param disease        the disease the damp-air rule watches for on that day; null outside its window
     */
    public record LatestResponse(String parcelId, Instant timestamp, double temperatureC, double humidityPct,
            double precipitationMm, Double soilTemperatureC, Double soilMoisturePct, double dewPointC,
            FrostLevel frostLevel, String crop, HumidityLevel humidityLevel, SensorMode mode, String phase,
            Double frostWarningC, Double frostCriticalC, String disease) {
    }

    public record ParcelRequest(String name, String crop) {
    }

    /** Advice from the backend (IRRIGATION: soil water, SOWING: soil warm enough), to be sent like the alerts. */
    public record AdviceRequest(AlertType type, Instant timestamp, FrostLevel level, double temperatureC,
            double humidityPct, double dewPointC, String message) {
    }

    private final ParcelRegistry parcels;

    private final SensorStore store;
    private final SensorSimulator simulator;
    private final AlertService alertService;

    public SensorController(ParcelRegistry parcels, SensorStore store, SensorSimulator simulator,
            AlertService alertService) {
        this.parcels = parcels;
        this.store = store;
        this.simulator = simulator;
        this.alertService = alertService;
    }

    @GetMapping("/sensors/parcels/{id}/latest")
    public LatestResponse latest(@PathVariable String id) {
        requireParcel(id);
        SensorStore.Status st = store.latest(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "No readings yet for " + id));
        Reading r = st.reading();
        AppProperties.Crop crop = parcels.cropFor(id);
        AppProperties.Phase phase = CropCalendar.phase(crop, r.timestamp());
        AppProperties.Disease disease = crop.disease();
        boolean diseaseWatched = disease != null && CropCalendar.within(disease.from(), disease.to(), r.timestamp());
        return new LatestResponse(r.parcelId(), r.timestamp(), r.temperatureC(), r.humidityPct(), r.precipitationMm(),
                r.soilTemperatureC(), r.soilMoisturePct(), Math.round(st.assessment().dewPointC() * 10) / 10.0, st.assessment().level(),
                parcels.cropKey(id), st.humidity(), simulator.mode(id), phase.name(), phase.frostWarningC(),
                phase.frostCriticalC(), diseaseWatched ? disease.name() : null);
    }

    @GetMapping("/sensors/parcels")
    public List<AppProperties.Parcel> parcels() {
        return parcels.all();
    }

    /** The backend registers its parcels here, so a parcel created in the web app gets a sensor. */
    @PutMapping("/sensors/parcels/{id}")
    public AppProperties.Parcel register(@PathVariable String id, @RequestBody ParcelRequest body) {
        AppProperties.Parcel parcel = parcels.put(id, body.name(), body.crop());
        simulator.ensureSensor(id);
        return parcel;
    }

    @GetMapping("/sensors/parcels/{id}/readings")
    public List<Reading> readings(@PathVariable String id, @RequestParam(defaultValue = "60") int minutes) {
        requireParcel(id);
        return store.readings(id, minutes);
    }

    @GetMapping("/alerts")
    public List<Alert> alerts(@RequestParam(required = false) String parcelId,
            @RequestParam(defaultValue = "FROST") String type) {
        Stream<Alert> alerts;
        if (parcelId == null) {
            alerts = store.alerts().stream();
        } else {
            requireParcel(parcelId);
            alerts = store.alerts(parcelId).stream();
        }
        // FROST by default: existing clients label every alert as a frost alert.
        return switch (type.toUpperCase()) {
            case "ALL" -> alerts.toList();
            case "FROST" -> alerts.filter(a -> a.type() == AlertType.FROST).toList();
            case "HUMIDITY" -> alerts.filter(a -> a.type() == AlertType.HUMIDITY_HIGH || a.type() == AlertType.HUMIDITY_LOW)
                    .toList();
            case "IRRIGATION" -> alerts.filter(a -> a.type() == AlertType.IRRIGATION).toList();
            case "SOWING" -> alerts.filter(a -> a.type() == AlertType.SOWING).toList();
            default -> throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "type must be FROST, HUMIDITY, IRRIGATION, SOWING or ALL");
        };
    }

    /**
     * The backend's advice for a parcel (IRRIGATION or SOWING): stored and sent to Telegram like the other alerts.
     * Sending the same advice again does nothing ({"sent": false}).
     */
    @PostMapping("/sensors/parcels/{id}/advice")
    public Map<String, Object> advice(@PathVariable String id, @RequestBody AdviceRequest body) {
        requireParcel(id);
        if (body.type() != AlertType.IRRIGATION && body.type() != AlertType.SOWING) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "type must be IRRIGATION or SOWING");
        }
        if (body.timestamp() == null || body.level() == null || body.message() == null || body.message().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "timestamp, level and message are required");
        }
        Alert alert = new Alert(id, parcels.name(id), parcels.cropKey(id), body.type(), body.level(),
                body.temperatureC(), body.humidityPct(), body.dewPointC(), body.timestamp(), body.message());
        return Map.of("sent", alertService.sendExternal(alert));
    }

    @PostMapping("/demo/frost/{parcelId}")
    public Map<String, Object> frost(@PathVariable String parcelId) {
        return switchMode(parcelId, SensorMode.FROST);
    }

    /** Replays a real damp spell of 2026 for the parcel's crop; 409 if the crop had none. */
    @PostMapping("/demo/humid/{parcelId}")
    public Map<String, Object> humid(@PathVariable String parcelId) {
        return switchMode(parcelId, SensorMode.HUMID);
    }

    /** Replays a real hot, dry spell of 2026 for the parcel's crop; 409 if the crop had none. */
    @PostMapping("/demo/dry/{parcelId}")
    public Map<String, Object> dry(@PathVariable String parcelId) {
        return switchMode(parcelId, SensorMode.DRY);
    }

    @PostMapping("/demo/replay/{parcelId}")
    public Map<String, Object> replay(@PathVariable String parcelId) {
        return switchMode(parcelId, SensorMode.REPLAY);
    }

    /** Demo watering: the soil moisture rises to field capacity, without rain; 409 while a replay runs. */
    @PostMapping("/demo/irrigate/{parcelId}")
    public Map<String, Object> irrigate(@PathVariable String parcelId) {
        requireParcel(parcelId);
        try {
            simulator.irrigate(parcelId);
        } catch (SensorSimulator.DemoRefusedException e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, e.getMessage(), e);
        }
        return Map.of("parcelId", parcelId, "mode", simulator.mode(parcelId));
    }

    /** Back to normal weather for one parcel; unlike reset, the all-clear messages are sent. */
    @PostMapping("/demo/normal/{parcelId}")
    public Map<String, Object> normal(@PathVariable String parcelId) {
        return switchMode(parcelId, SensorMode.NORMAL);
    }

    @PostMapping("/demo/reset")
    public Map<String, Object> reset() {
        // Modes first, so a frost reading cannot re-raise an alert right after the clear.
        simulator.setAll(SensorMode.NORMAL);
        alertService.reset();
        return Map.of("mode", SensorMode.NORMAL);
    }

    private Map<String, Object> switchMode(String parcelId, SensorMode mode) {
        requireParcel(parcelId);
        try {
            simulator.setMode(parcelId, mode);
        } catch (SensorSimulator.DemoRefusedException e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, e.getMessage(), e);
        } catch (IllegalStateException e) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, e.getMessage(), e);
        }
        return Map.of("parcelId", parcelId, "mode", mode);
    }

    private void requireParcel(String id) {
        if (!simulator.hasParcel(id)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown parcel " + id);
        }
    }
}
