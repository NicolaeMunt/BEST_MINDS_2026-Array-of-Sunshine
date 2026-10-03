package md.agro.sensors.model;

import java.time.Instant;

public record Reading(String parcelId, Instant timestamp, double temperatureC, double humidityPct) {
}
