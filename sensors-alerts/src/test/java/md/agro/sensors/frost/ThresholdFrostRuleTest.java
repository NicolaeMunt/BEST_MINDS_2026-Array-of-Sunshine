package md.agro.sensors.frost;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.List;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.model.Reading;
import org.junit.jupiter.api.Test;

class ThresholdFrostRuleTest {

    private static final Instant T0 = Instant.parse("2025-04-09T00:00:00Z");

    private final FrostRule rule = new ThresholdFrostRule(new AppProperties.Frost(2, 0, 5, 3, 3, 1800));

    private static Reading at(int minute, double temp) {
        return new Reading("P1", T0.plusSeconds(minute * 60L), temp, 85);
    }

    @Test
    void levelsByTemperature() {
        assertEquals(FrostLevel.OK, rule.evaluate(at(0, 2.1), List.of()).level());
        assertEquals(FrostLevel.WARNING, rule.evaluate(at(0, 2.0), List.of()).level());
        assertEquals(FrostLevel.WARNING, rule.evaluate(at(0, 0.1), List.of()).level());
        assertEquals(FrostLevel.CRITICAL, rule.evaluate(at(0, 0.0), List.of()).level());
        assertEquals(FrostLevel.CRITICAL, rule.evaluate(at(0, -2.5), List.of()).level());
    }

    @Test
    void warningWhenFallingFastBelowFive() {
        FrostAssessment a = rule.evaluate(at(50, 4.5), List.of(at(0, 8.0), at(25, 6.0)));
        assertEquals(FrostLevel.WARNING, a.level());
        assertTrue(a.falling());
    }

    @Test
    void okWhenFallingSlowlyOrStillWarm() {
        assertEquals(FrostLevel.OK, rule.evaluate(at(50, 4.5), List.of(at(0, 6.5))).level());
        assertEquals(FrostLevel.OK, rule.evaluate(at(50, 5.5), List.of(at(0, 10.0))).level());
    }

    @Test
    void dropOlderThanOneHourIsIgnored() {
        assertEquals(FrostLevel.OK, rule.evaluate(at(90, 4.5), List.of(at(0, 9.0), at(60, 5.0))).level());
    }

    @Test
    void recoveringAfterFrostIsNotFalling() {
        FrostAssessment a = rule.evaluate(at(50, 4.0), List.of(at(0, 9.0), at(20, -2.0), at(40, 1.0)));
        assertEquals(FrostLevel.OK, a.level());
        assertFalse(rule.evaluate(at(50, 4.0), List.of(at(20, -2.0))).falling());
    }

    @Test
    void dewPointMagnus() {
        assertEquals(20.0, ThresholdFrostRule.dewPoint(20, 100), 0.01);
        assertEquals(9.3, ThresholdFrostRule.dewPoint(20, 50), 0.1);
        assertEquals(-0.6, ThresholdFrostRule.dewPoint(1.2, 88), 0.1);
    }
}
