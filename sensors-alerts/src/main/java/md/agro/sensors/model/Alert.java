package md.agro.sensors.model;

import java.time.Instant;

import md.agro.sensors.frost.FrostLevel;

/**
 * A notification that was sent. Level OK means "all clear"; humidity alerts are always WARNING.
 *
 * @param crop crop key of the parcel, e.g. wheat
 */
public record Alert(
        String parcelId,
        String parcelName,
        String crop,
        AlertType type,
        FrostLevel level,
        double temperatureC,
        double humidityPct,
        double dewPointC,
        Instant timestamp,
        String message) {
}
