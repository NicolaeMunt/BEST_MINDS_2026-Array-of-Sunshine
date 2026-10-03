package md.agro.sensors.humidity;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.Instant;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.model.Reading;
import org.junit.jupiter.api.Test;

class ThresholdHumidityRuleTest {

    private final HumidityRule rule = new ThresholdHumidityRule(new AppProperties.Humidity(10, 5));

    private static Reading reading(double temp, double humidity) {
        return new Reading("P1", Instant.parse("2025-06-01T12:00:00Z"), temp, humidity);
    }

    private static AppProperties.Crop crop(double low, double high) {
        return new AppProperties.Crop("test", 2, 0, low, high, "", "", "");
    }

    @Test
    void levelsByHumidity() {
        AppProperties.Crop crop = crop(30, 85);
        assertEquals(HumidityLevel.LOW, rule.evaluate(reading(25, 30), crop));
        assertEquals(HumidityLevel.OK, rule.evaluate(reading(25, 31), crop));
        assertEquals(HumidityLevel.OK, rule.evaluate(reading(18, 84), crop));
        assertEquals(HumidityLevel.HIGH, rule.evaluate(reading(18, 85), crop));
    }

    @Test
    void sameHumidityDifferentLevelPerCrop() {
        assertEquals(HumidityLevel.HIGH, rule.evaluate(reading(18, 82), crop(30, 80)));
        assertEquals(HumidityLevel.OK, rule.evaluate(reading(18, 82), crop(30, 85)));
        assertEquals(HumidityLevel.LOW, rule.evaluate(reading(30, 33), crop(35, 85)));
        assertEquals(HumidityLevel.OK, rule.evaluate(reading(30, 33), crop(25, 85)));
    }

    @Test
    void humidButColdIsNotDiseaseRisk() {
        assertEquals(HumidityLevel.OK, rule.evaluate(reading(1, 95), crop(30, 85)));
        assertEquals(HumidityLevel.HIGH, rule.evaluate(reading(10, 95), crop(30, 85)));
    }
}
