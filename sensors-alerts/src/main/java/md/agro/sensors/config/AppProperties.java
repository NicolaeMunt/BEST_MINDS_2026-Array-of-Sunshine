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
        @DefaultValue Telegram telegram,
        @DefaultValue("*") List<String> corsOrigins) {

    /** Used for parcels whose crop is missing or not listed under app.crops. */
    public static final Crop DEFAULT_CROP = new Crop("cultură", 2, 0, 30, 85,
            "Pregătiți măsurile de protecție.",
            "Risc de boli fungice. Verificați cultura.",
            "Risc de stres hidric. Irigați dacă este posibil.");

    /** @param crop key into app.crops, e.g. wheat */
    public record Parcel(String id, String name, @DefaultValue("") String crop) {
    }

    /**
     * Alert thresholds and advice texts of one crop.
     *
     * @param name Romanian name used in messages
     */
    public record Crop(
            @DefaultValue("cultură") String name,
            @DefaultValue("2") double frostWarningC,
            @DefaultValue("0") double frostCriticalC,
            @DefaultValue("30") double humidityLowPct,
            @DefaultValue("85") double humidityHighPct,
            @DefaultValue("Pregătiți măsurile de protecție.") String frostAdvice,
            @DefaultValue("Risc de boli fungice. Verificați cultura.") String humidAdvice,
            @DefaultValue("Risc de stres hidric. Irigați dacă este posibil.") String dryAdvice) {
    }

    public record Simulator(
            @DefaultValue("5") double intervalSeconds,
            @DefaultValue("60") double frostRampSeconds,
            @DefaultValue("classpath:replay/sample-frost-night.csv") String replayFile,
            @DefaultValue("10") double replaySecondsPerHour,
            @DefaultValue("720") int maxReadingsPerParcel) {
    }

    /** Frost settings shared by all crops; the temperature thresholds themselves are per crop. */
    public record Frost(
            @DefaultValue("3") double fallingMarginC,
            @DefaultValue("3") double fallingDropC,
            @DefaultValue("1") double allClearMarginC,
            @DefaultValue("1800") long cooldownSeconds) {
    }

    public record Humidity(
            @DefaultValue("10") double diseaseMinTempC,
            @DefaultValue("5") double clearMarginPct) {
    }

    public record Telegram(
            @DefaultValue("") String token,
            @DefaultValue("") String username,
            @DefaultValue("") String fallbackChatId,
            @DefaultValue("telegram-chats.txt") String chatsFile) {
    }

}
