package md.agro.sensors.humidity;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.model.Reading;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class ThresholdHumidityRule implements HumidityRule {

    private final AppProperties.Humidity cfg;

    @Autowired
    public ThresholdHumidityRule(AppProperties props) {
        this(props.humidity());
    }

    public ThresholdHumidityRule(AppProperties.Humidity cfg) {
        this.cfg = cfg;
    }

    @Override
    public HumidityLevel evaluate(Reading current, AppProperties.Crop crop) {
        if (current.humidityPct() <= crop.humidityLowPct()) {
            return HumidityLevel.LOW;
        }
        // Humid but cold air (a frost night) is not a disease risk: fungi need warmth.
        if (current.humidityPct() >= crop.humidityHighPct() && current.temperatureC() >= cfg.diseaseMinTempC()) {
            return HumidityLevel.HIGH;
        }
        return HumidityLevel.OK;
    }
}
