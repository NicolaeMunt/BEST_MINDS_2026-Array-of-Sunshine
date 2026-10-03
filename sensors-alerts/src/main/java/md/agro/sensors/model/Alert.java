package md.agro.sensors.model;

import java.time.Instant;

import md.agro.sensors.frost.FrostLevel;

/** A notification that was sent. Level OK means "all clear". */
public record Alert(
        String parcelId,
        String parcelName,
        FrostLevel level,
        double temperatureC,
        double humidityPct,
        double dewPointC,
        Instant timestamp,
        String message) {
}
