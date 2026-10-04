package md.agro.sensors.config;

import java.util.List;
import java.util.Map;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties("app")
public record AppProperties(
        @DefaultValue List<Parcel> parcels,
        @DefaultValue Map<String, Crop> crops,
        @DefaultValue Simulator simulator,
        @DefaultValue Frost frost,
        @DefaultValue Humidity humidity,
        @DefaultValue Water water,
        @DefaultValue Telegram telegram,
        @DefaultValue("*") List<String> corsOrigins) {

    /** Used for parcels whose crop is missing or not listed under app.crops: frost at 2 / 0 °C all year, nothing else. */
    public static final Crop DEFAULT_CROP = new Crop("cultură", "Pregătiți măsurile de protecție.",
            List.of(new Phase("01-01", "sezon", "growing", 2.0, 0.0, null, null)), null, null);

    /** @param crop key into app.crops, e.g. wheat */
    public record Parcel(String id, String name, @DefaultValue("") String crop) {
    }

    /**
     * The rules of one crop: its phases on the calendar, the disease its damp-air rule watches for and when
     * dry, hot air harms it.
     *
     * @param name    Romanian name used in messages
     * @param phases  in calendar order; the first one should start on 01-01
     * @param disease null: no damp-air rule
     * @param dry     null: no dry-air rule
     */
    public record Crop(
            @DefaultValue("cultură") String name,
            @DefaultValue("Pregătiți măsurile de protecție.") String frostAdvice,
            @DefaultValue List<Phase> phases,
            Disease disease,
            Window dry) {
    }

    /**
     * A phase starts on {@code from} (month-day, e.g. 05-15) and lasts until the next one starts.
     *
     * @param frostWarningC  with frostCriticalC: the frost thresholds in this phase; null when frost does no harm
     * @param season         what the satellite job expects in this phase; not used here
     * @param kc             FAO-56 crop coefficient for the backend's water balance; not used here
     * @param frostAdvice    what to do about frost in this phase; null: the crop's frostAdvice
     */
    public record Phase(String from, String name, @DefaultValue("growing") String season,
            Double frostWarningC, Double frostCriticalC, Double kc, String frostAdvice) {

        public boolean frostHarms() {
            return frostWarningC != null && frostCriticalC != null;
        }

        public String frostAdvice(Crop crop) {
            return frostAdvice != null ? frostAdvice : crop.frostAdvice();
        }
    }

    /**
     * Damp air between {@code from} and {@code to} (month-day) raises the risk of this disease. Damp means
     * at least minHumidityPct, standing in for wet leaves. Any one condition is enough.
     */
    public record Disease(String name, String from, String to, @DefaultValue("90") double minHumidityPct,
            @DefaultValue List<Condition> conditions, @DefaultValue("") String advice) {
    }

    /** At least {@code hours} damp hours among the last {@code withinHours}, at minTempC..maxTempC. */
    public record Condition(int hours, int withinHours, double minTempC, double maxTempC) {
    }

    /** Month-days {@code from}..{@code to}, both included. */
    public record Window(String from, String to, @DefaultValue("") String advice) {
    }

    /**
     * @param episodeFile     HUMID and DRY replay this file; {mode} becomes humid or dry, {crop} the crop key
     * @param soilMoisturePct soil moisture of the live sensors until a replay or a watering changes it
     * @param soilLagHours    the live soil temperature follows the air this slowly
     * @param wateringSeconds a demo watering brings the soil moisture up to field capacity in this time
     */
    public record Simulator(
            @DefaultValue("5") double intervalSeconds,
            @DefaultValue("60") double frostRampSeconds,
            @DefaultValue("classpath:replay/sample-frost-night.csv") String replayFile,
            @DefaultValue("10") double replaySecondsPerHour,
            @DefaultValue("classpath:replay/{mode}-{crop}.csv") String episodeFile,
            @DefaultValue("0.5") double episodeSecondsPerHour,
            @DefaultValue("720") int maxReadingsPerParcel,
            @DefaultValue("23") double soilMoisturePct,
            @DefaultValue("6") double soilLagHours,
            @DefaultValue("30") double wateringSeconds) {
    }

    /** The soil of the parcels (FAO-56 silt loam); here only the demo watering uses it. */
    public record Water(
            @DefaultValue("27") double fieldCapacityPct,
            @DefaultValue("10") double wiltingPointPct,
            @DefaultValue("3") double wateringRisePct) {
    }

    /** Frost settings shared by all crops; the temperature thresholds themselves are per crop and phase. */
    public record Frost(
            @DefaultValue("3") double fallingMarginC,
            @DefaultValue("3") double fallingDropC,
            @DefaultValue("1") double allClearMarginC,
            @DefaultValue("1800") long cooldownSeconds) {
    }

    /**
     * Dry, hot air: at most dryMaxPct humidity at dryMinTempC or warmer. A disease or dry-air risk lasts
     * holdHours after its conditions were last met.
     */
    public record Humidity(
            @DefaultValue("30") double dryMaxPct,
            @DefaultValue("25") double dryMinTempC,
            @DefaultValue("24") int holdHours) {
    }

    public record Telegram(
            @DefaultValue("") String token,
            @DefaultValue("") String username,
            @DefaultValue("") String fallbackChatId,
            @DefaultValue("telegram-chats.txt") String chatsFile) {
    }

}
