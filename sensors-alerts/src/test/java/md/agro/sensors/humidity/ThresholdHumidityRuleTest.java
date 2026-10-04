package md.agro.sensors.humidity;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.model.Reading;
import org.junit.jupiter.api.Test;

class ThresholdHumidityRuleTest {

    private final HumidityRule rule = new ThresholdHumidityRule(new AppProperties.Humidity(30, 25, 24));

    // Inside both windows below: 10 June, local time.
    private static final Instant JUNE = Instant.parse("2026-06-10T00:00:00Z");
    private static final Instant SEPTEMBER = Instant.parse("2026-09-10T00:00:00Z");

    /** Disease after 6 damp hours in a row at 18-27 °C (like corn leaf blight); dry air hurts from June to August. */
    private static final AppProperties.Crop CROP = new AppProperties.Crop("test", "", List.of(), new AppProperties.Disease(
            "boala", "06-01", "08-31", 90, List.of(new AppProperties.Condition(6, 6, 18, 27)), ""),
            new AppProperties.Window("06-01", "08-31", ""));

    /** Hourly readings, the last one being {@code current}. */
    private static List<Reading> hourly(Instant start, double temp, double... humidity) {
        List<Reading> rows = new ArrayList<>();
        for (int i = 0; i < humidity.length; i++) {
            rows.add(new Reading("P1", start.plusSeconds(3600L * i), temp, humidity[i]));
        }
        return rows;
    }

    private HumidityAssessment last(List<Reading> rows, AppProperties.Crop crop) {
        return rule.evaluate(rows.get(rows.size() - 1), rows.subList(0, rows.size() - 1), crop);
    }

    @Test
    void diseaseRiskAfterEnoughDampHours() {
        assertEquals(HumidityLevel.OK, last(hourly(JUNE, 20, 95, 95, 95, 95, 95), CROP).level());
        HumidityAssessment h = last(hourly(JUNE, 20, 95, 95, 95, 95, 95, 95), CROP);
        assertEquals(HumidityLevel.HIGH, h.level());
        assertEquals(6, h.dampHours());
        assertEquals(6, h.withinHours());
    }

    @Test
    void riskHoldsForADayAfterTheDampHours() {
        // Six damp hours, then dry air: still HIGH 24 hours after the last damp hour, OK after 25.
        double[] humidity = new double[31];
        java.util.Arrays.fill(humidity, 60);
        java.util.Arrays.fill(humidity, 0, 6, 95);
        List<Reading> rows = hourly(JUNE, 20, humidity);
        assertEquals(HumidityLevel.HIGH, last(rows.subList(0, 30), CROP).level());
        assertEquals(HumidityLevel.OK, last(rows, CROP).level());
    }

    @Test
    void oneDryHourBreaksARunThatMustBeUnbroken() {
        assertEquals(HumidityLevel.OK, last(hourly(JUNE, 20, 95, 95, 95, 70, 95, 95, 95), CROP).level());
    }

    @Test
    void dampButTooColdOrOutsideTheWindowIsNoRisk() {
        assertEquals(HumidityLevel.OK, last(hourly(JUNE, 12, 95, 95, 95, 95, 95, 95), CROP).level());
        assertEquals(HumidityLevel.OK, last(hourly(SEPTEMBER, 20, 95, 95, 95, 95, 95, 95), CROP).level());
    }

    @Test
    void anyConditionIsEnough() {
        // Like apple scab: 6 hours at 16-24 °C, or 12 hours from 9 °C up.
        AppProperties.Crop scab = new AppProperties.Crop("test", "", List.of(), new AppProperties.Disease("rapăn", "04-01",
                "06-30", 90, List.of(new AppProperties.Condition(6, 6, 16, 24), new AppProperties.Condition(12, 12, 9, 24)), ""),
                null);
        assertEquals(HumidityLevel.HIGH, last(hourly(JUNE, 18, 92, 92, 92, 92, 92, 92), scab).level());
        assertEquals(HumidityLevel.OK, last(hourly(JUNE, 11, 92, 92, 92, 92, 92, 92), scab).level());
        assertEquals(HumidityLevel.HIGH, last(hourly(JUNE, 11, 92, 92, 92, 92, 92, 92, 92, 92, 92, 92, 92, 92), scab).level());
    }

    @Test
    void hourCountsWhenItsAverageIsDamp() {
        // Readings every 20 minutes; the hours average 95%, 95%, ... even though one reading in each is 85%.
        List<Reading> rows = new ArrayList<>();
        for (int i = 0; i < 18; i++) {
            rows.add(new Reading("P1", JUNE.plusSeconds(1200L * i), 20, i % 3 == 0 ? 85 : 100));
        }
        assertEquals(HumidityLevel.HIGH, last(rows, CROP).level());
    }

    @Test
    void dryHotAirInsideTheDryWindow() {
        assertEquals(HumidityLevel.LOW, last(hourly(JUNE, 30, 50, 28), CROP).level());
        // Dry but not hot, or hot but not dry.
        assertEquals(HumidityLevel.OK, last(hourly(JUNE, 22, 50, 28), CROP).level());
        assertEquals(HumidityLevel.OK, last(hourly(JUNE, 30, 50, 35), CROP).level());
        assertEquals(HumidityLevel.OK, last(hourly(SEPTEMBER, 30, 50, 28), CROP).level());
    }

    @Test
    void dryEpisodeHoldsForADay() {
        // A dry afternoon, then a damp night: still LOW 23 hours later, OK after 24.
        List<Reading> rows = hourly(JUNE, 30, 25);
        rows.add(new Reading("P1", JUNE.plusSeconds(3600L * 23), 15, 80));
        assertEquals(HumidityLevel.LOW, last(rows, CROP).level());
        rows.set(1, new Reading("P1", JUNE.plusSeconds(3600L * 25), 15, 80));
        assertEquals(HumidityLevel.OK, last(rows, CROP).level());
    }
}
