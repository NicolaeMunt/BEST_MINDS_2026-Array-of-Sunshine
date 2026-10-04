package md.agro.sensors.model;

import java.time.Instant;

/** @param precipitationMm rain since the previous reading; 0 for the simulated readings */
public record Reading(String parcelId, Instant timestamp, double temperatureC, double humidityPct, double precipitationMm) {

    public Reading(String parcelId, Instant timestamp, double temperatureC, double humidityPct) {
        this(parcelId, timestamp, temperatureC, humidityPct, 0);
    }
}
