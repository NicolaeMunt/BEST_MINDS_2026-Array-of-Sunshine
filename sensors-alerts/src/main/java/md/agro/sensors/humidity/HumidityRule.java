package md.agro.sensors.humidity;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.model.Reading;

/** Same idea as FrostRule: the thresholds can be tuned without touching anything else. */
public interface HumidityRule {

    HumidityLevel evaluate(Reading current, AppProperties.Crop crop);
}
