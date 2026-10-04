package md.agro.sensors.frost;

import java.util.List;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.model.Reading;

/** Thresholds live behind this interface so they can be tuned without touching anything else. */
public interface FrostRule {

    /**
     * @param current the new reading
     * @param history earlier readings of the same parcel, oldest first (without {@code current})
     * @param crop    the crop grown on the parcel; its phase on the reading's day gives the thresholds
     */
    FrostAssessment evaluate(Reading current, List<Reading> history, AppProperties.Crop crop);
}
