package md.agro.sensors.humidity;

import java.util.List;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.model.Reading;

/** Same idea as FrostRule: the thresholds can be tuned without touching anything else. */
public interface HumidityRule {

    /**
     * @param history earlier readings of the same parcel, oldest first (without {@code current})
     */
    HumidityAssessment evaluate(Reading current, List<Reading> history, AppProperties.Crop crop);
}
