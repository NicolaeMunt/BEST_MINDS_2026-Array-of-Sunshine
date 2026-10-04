package md.agro.sensors.model;

import java.time.Instant;

/**
 * One reading of a parcel's sensor: the air, the rain and the soil probe.
 *
 * @param precipitationMm  rain since the previous reading; 0 for the simulated live readings
 * @param soilTemperatureC soil at ~5 cm (seed depth); null when the sensor has no soil probe
 * @param soilMoisturePct  soil water at ~20 cm, % of the soil volume; null when the sensor has no soil probe
 */
public record Reading(String parcelId, Instant timestamp, double temperatureC, double humidityPct, double precipitationMm,
        Double soilTemperatureC, Double soilMoisturePct) {

    public Reading(String parcelId, Instant timestamp, double temperatureC, double humidityPct) {
        this(parcelId, timestamp, temperatureC, humidityPct, 0, null, null);
    }
}
