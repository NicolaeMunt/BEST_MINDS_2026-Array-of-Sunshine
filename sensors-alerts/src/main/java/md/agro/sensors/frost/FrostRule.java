package md.agro.sensors.frost;

import java.util.List;

import md.agro.sensors.model.Reading;

/** Thresholds live behind this interface so they can be tuned without touching anything else. */
public interface FrostRule {

    /**
     * @param current the new reading
     * @param history earlier readings of the same parcel, oldest first (without {@code current})
     */
    FrostAssessment evaluate(Reading current, List<Reading> history);
}
