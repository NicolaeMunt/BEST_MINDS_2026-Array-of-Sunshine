package md.agro.sensors.frost;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.List;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.config.CropCalendar;
import md.agro.sensors.model.Reading;
import org.junit.jupiter.api.Test;

class ThresholdFrostRuleTest {

    // 03:00 local time on 9 April.
    private static final Instant T0 = Instant.parse("2025-04-09T00:00:00Z");
    // Warning at 2 °C, critical at 0 °C, all year.
    private static final AppProperties.Crop CROP = AppProperties.DEFAULT_CROP;

    private final FrostRule rule = new ThresholdFrostRule(new AppProperties.Frost(3, 3, 1, 1800));

    private static Reading at(int minute, double temp) {
        return new Reading("P1", T0.plusSeconds(minute * 60L), temp, 85);
    }

    private static Reading on(String isoUtc, double temp) {
        return new Reading("P1", Instant.parse(isoUtc), temp, 85);
    }

    private static AppProperties.Crop crop(double frostWarningC, double frostCriticalC) {
        return new AppProperties.Crop("test", "", List.of(phase("01-01", frostWarningC, frostCriticalC)), null, null, null);
    }

    private static AppProperties.Phase phase(String from, Double warning, Double critical) {
        return new AppProperties.Phase(from, "faza " + from, "growing", warning, critical, null, null);
    }

    /** Wheat-like: hardy until May, sensitive while it flowers, frost-proof after the harvest. */
    private static final AppProperties.Crop WHEAT = new AppProperties.Crop("grâu", "", List.of(
            phase("01-01", null, null),
            phase("03-15", -9.0, -11.0),
            phase("05-15", 1.0, -1.0),
            phase("07-15", null, null)), null, null, null);

    @Test
    void levelsByTemperature() {
        assertEquals(FrostLevel.OK, rule.evaluate(at(0, 2.1), List.of(), CROP).level());
        assertEquals(FrostLevel.WARNING, rule.evaluate(at(0, 2.0), List.of(), CROP).level());
        assertEquals(FrostLevel.WARNING, rule.evaluate(at(0, 0.1), List.of(), CROP).level());
        assertEquals(FrostLevel.CRITICAL, rule.evaluate(at(0, 0.0), List.of(), CROP).level());
        assertEquals(FrostLevel.CRITICAL, rule.evaluate(at(0, -2.5), List.of(), CROP).level());
    }

    @Test
    void sameTemperatureDifferentLevelPerCrop() {
        AppProperties.Crop hardy = crop(0, -3);
        AppProperties.Crop sensitive = crop(3, 0);
        assertEquals(FrostLevel.OK, rule.evaluate(at(0, 1.0), List.of(), hardy).level());
        assertEquals(FrostLevel.WARNING, rule.evaluate(at(0, 1.0), List.of(), sensitive).level());
        assertEquals(FrostLevel.WARNING, rule.evaluate(at(0, -1.0), List.of(), hardy).level());
        assertEquals(FrostLevel.CRITICAL, rule.evaluate(at(0, -1.0), List.of(), sensitive).level());
    }

    @Test
    void sameTemperatureDifferentLevelPerPhase() {
        // -2 °C: harmless while tillering, critical in flower, harmless after the harvest and in winter.
        assertEquals(FrostLevel.OK, rule.evaluate(on("2026-04-01T00:00:00Z", -2), List.of(), WHEAT).level());
        assertEquals(FrostLevel.CRITICAL, rule.evaluate(on("2026-05-20T00:00:00Z", -2), List.of(), WHEAT).level());
        assertEquals(FrostLevel.OK, rule.evaluate(on("2026-09-30T00:00:00Z", -2), List.of(), WHEAT).level());
        assertEquals(FrostLevel.OK, rule.evaluate(on("2026-01-10T00:00:00Z", -15), List.of(), WHEAT).level());
        // Tillering wheat is only hurt by a hard frost.
        assertEquals(FrostLevel.CRITICAL, rule.evaluate(on("2026-04-01T00:00:00Z", -11.5), List.of(), WHEAT).level());
    }

    @Test
    void sowingLaterMovesTheCalendar() {
        AppProperties.Crop corn = new AppProperties.Crop("porumb", "", List.of(
                phase("01-01", null, null),
                phase("04-20", 0.0, -2.0),
                phase("09-20", null, null)), null, null, "04-20");
        Instant sept25 = Instant.parse("2026-09-25T00:00:00Z");
        // Calendar: on 25 September the crop is mature, frost does no harm.
        assertEquals(FrostLevel.OK, rule.evaluate(new Reading("P1", sept25, -3, 85), List.of(), corn).level());
        // Sown 20 days late (10 May): it is still five days before maturity, and -3 °C is critical.
        AppProperties.Crop late = CropCalendar.forSowing(corn, "2026-05-10");
        assertEquals(FrostLevel.CRITICAL, rule.evaluate(new Reading("P1", sept25, -3, 85), List.of(), late).level());
        assertEquals("faza 04-20", CropCalendar.phase(late, sept25).name());
        // A date far off is ignored, and so is a crop whose calendar does not depend on sowing.
        assertEquals(corn, CropCalendar.forSowing(corn, "2026-12-01"));
        assertEquals(WHEAT, CropCalendar.forSowing(WHEAT, "2026-05-10"));
    }

    @Test
    void phaseFollowsTheLocalDay() {
        // 14 May 21:30 UTC is already 15 May 00:30 in Chișinău (UTC+3): the flowering phase.
        assertEquals("faza 05-15", CropCalendar.phase(WHEAT, Instant.parse("2026-05-14T21:30:00Z")).name());
        assertEquals("faza 03-15", CropCalendar.phase(WHEAT, Instant.parse("2026-05-14T20:30:00Z")).name());
        assertTrue(CropCalendar.within("05-20", "06-15", Instant.parse("2026-06-15T20:00:00Z")));
        assertFalse(CropCalendar.within("05-20", "06-15", Instant.parse("2026-06-15T21:00:00Z")));
    }

    @Test
    void warningWhenFallingFastNearTheThreshold() {
        FrostAssessment a = rule.evaluate(at(50, 4.5), List.of(at(0, 8.0), at(25, 6.0)), CROP);
        assertEquals(FrostLevel.WARNING, a.level());
        assertTrue(a.falling());
        // The same drop is still far from the warning threshold of a hardy crop.
        assertEquals(FrostLevel.OK, rule.evaluate(at(50, 4.5), List.of(at(0, 8.0)), crop(0, -3)).level());
    }

    @Test
    void okWhenFallingSlowlyOrStillWarm() {
        assertEquals(FrostLevel.OK, rule.evaluate(at(50, 4.5), List.of(at(0, 6.5)), CROP).level());
        assertEquals(FrostLevel.OK, rule.evaluate(at(50, 5.5), List.of(at(0, 10.0)), CROP).level());
    }

    @Test
    void dropOlderThanOneHourIsIgnored() {
        assertEquals(FrostLevel.OK, rule.evaluate(at(90, 4.5), List.of(at(0, 9.0), at(60, 5.0)), CROP).level());
    }

    @Test
    void recoveringAfterFrostIsNotFalling() {
        FrostAssessment a = rule.evaluate(at(50, 4.0), List.of(at(0, 9.0), at(20, -2.0), at(40, 1.0)), CROP);
        assertEquals(FrostLevel.OK, a.level());
        assertFalse(rule.evaluate(at(50, 4.0), List.of(at(20, -2.0)), CROP).falling());
    }

    @Test
    void dewPointMagnus() {
        assertEquals(20.0, ThresholdFrostRule.dewPoint(20, 100), 0.01);
        assertEquals(9.3, ThresholdFrostRule.dewPoint(20, 50), 0.1);
        assertEquals(-0.6, ThresholdFrostRule.dewPoint(1.2, 88), 0.1);
    }
}
