package md.agro.sensors.web;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import md.agro.sensors.alert.AlertService;
import md.agro.sensors.frost.FrostLevel;
import md.agro.sensors.model.Alert;
import md.agro.sensors.model.Reading;
import md.agro.sensors.model.SensorMode;
import md.agro.sensors.sim.SensorSimulator;
import md.agro.sensors.store.SensorStore;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class SensorController {

    // Field names here are what Coder 3 sees; align with the shared JSON contract.
    public record LatestResponse(String parcelId, Instant timestamp, double temperatureC, double humidityPct,
            double dewPointC, FrostLevel frostLevel) {
    }

    private final SensorStore store;
    private final SensorSimulator simulator;
    private final AlertService alertService;

    public SensorController(SensorStore store, SensorSimulator simulator, AlertService alertService) {
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
        return new LatestResponse(r.parcelId(), r.timestamp(), r.temperatureC(), r.humidityPct(),
                Math.round(st.assessment().dewPointC() * 10) / 10.0, st.assessment().level());
    }

    @GetMapping("/sensors/parcels/{id}/readings")
    public List<Reading> readings(@PathVariable String id, @RequestParam(defaultValue = "60") int minutes) {
        requireParcel(id);
        return store.readings(id, minutes);
    }

    @GetMapping("/alerts")
    public List<Alert> alerts(@RequestParam(required = false) String parcelId) {
        if (parcelId == null) {
            return store.alerts();
        }
        requireParcel(parcelId);
        return store.alerts(parcelId);
    }

    @PostMapping("/demo/frost/{parcelId}")
    public Map<String, Object> frost(@PathVariable String parcelId) {
        return switchMode(parcelId, SensorMode.FROST);
    }

    @PostMapping("/demo/replay/{parcelId}")
    public Map<String, Object> replay(@PathVariable String parcelId) {
        return switchMode(parcelId, SensorMode.REPLAY);
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
