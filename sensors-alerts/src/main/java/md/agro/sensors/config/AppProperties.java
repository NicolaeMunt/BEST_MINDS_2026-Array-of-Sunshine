package md.agro.sensors.config;

import java.util.List;
import java.util.Optional;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties("app")
public record AppProperties(
        @DefaultValue List<Parcel> parcels,
        @DefaultValue Simulator simulator,
        @DefaultValue Frost frost,
        @DefaultValue Telegram telegram,
        @DefaultValue("*") List<String> corsOrigins) {

    public record Parcel(String id, String name) {
    }

    public record Simulator(
            @DefaultValue("5") double intervalSeconds,
            @DefaultValue("60") double frostRampSeconds,
            @DefaultValue("classpath:replay/sample-frost-night.csv") String replayFile,
            @DefaultValue("10") double replaySecondsPerHour,
            @DefaultValue("720") int maxReadingsPerParcel) {
    }

    public record Frost(
            @DefaultValue("2") double warningTempC,
            @DefaultValue("0") double criticalTempC,
            @DefaultValue("5") double fallingBelowC,
            @DefaultValue("3") double fallingDropC,
            @DefaultValue("3") double allClearTempC,
            @DefaultValue("1800") long cooldownSeconds) {
    }

    public record Telegram(
            @DefaultValue("") String token,
            @DefaultValue("") String username,
            @DefaultValue("") String fallbackChatId) {
    }

    public Optional<Parcel> parcel(String id) {
        return parcels.stream().filter(p -> p.id().equalsIgnoreCase(id)).findFirst();
    }
}
