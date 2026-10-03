package md.agro.sensors.alert;

import java.util.Locale;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.frost.FrostAssessment;
import md.agro.sensors.frost.FrostLevel;
import md.agro.sensors.humidity.HumidityLevel;
import md.agro.sensors.model.AlertType;
import md.agro.sensors.model.Reading;

/** Romanian texts sent to the farmer. */
public final class Messages {

    private Messages() {
    }

    public static String frost(String parcelName, AppProperties.Crop crop, Reading r, FrostAssessment a) {
        String title = title(parcelName, crop);
        return switch (a.level()) {
            case CRITICAL -> "❄️ ÎNGHEȚ – %s\nTemperatura: %s °C (prag critic %s: %s °C)"
                    .formatted(title, num(r.temperatureC()), crop.name(), num(crop.frostCriticalC()));
            case WARNING -> "⚠️ Risc de îngheț – %s\nTemperatura: %s °C%s\nUmiditate: %.0f%% · Punct de rouă: %s °C\n%s"
                    .formatted(title, num(r.temperatureC()), a.falling() ? " (în scădere)" : "",
                            r.humidityPct(), num(a.dewPointC()), crop.frostAdvice());
            case OK -> frostAllClear(parcelName, crop, r);
        };
    }

    public static String frostAllClear(String parcelName, AppProperties.Crop crop, Reading r) {
        return "✅ Pericol trecut – %s\nTemperatura: %s °C".formatted(title(parcelName, crop), num(r.temperatureC()));
    }

    public static String humidity(String parcelName, AppProperties.Crop crop, Reading r, AlertType type) {
        boolean high = type == AlertType.HUMIDITY_HIGH;
        return "%s – %s\nUmiditate: %.0f%% (prag %s: %.0f%%) · Temperatura: %s °C\n%s".formatted(
                high ? "💧 Umiditate ridicată" : "🌵 Umiditate scăzută", title(parcelName, crop),
                r.humidityPct(), crop.name(), high ? crop.humidityHighPct() : crop.humidityLowPct(),
                num(r.temperatureC()), high ? crop.humidAdvice() : crop.dryAdvice());
    }

    public static String humidityAllClear(String parcelName, AppProperties.Crop crop, Reading r) {
        return "✅ Umiditate revenită la normal – %s\nUmiditate: %.0f%%"
                .formatted(title(parcelName, crop), r.humidityPct());
    }

    public static String status(FrostLevel level) {
        return switch (level) {
            case OK -> "✅ OK";
            case WARNING -> "⚠️ Risc de îngheț";
            case CRITICAL -> "❄️ Îngheț";
        };
    }

    public static String status(HumidityLevel level) {
        return switch (level) {
            case OK -> "normală";
            case LOW -> "🌵 scăzută";
            case HIGH -> "💧 ridicată";
        };
    }

    public static String num(double v) {
        return String.format(Locale.ROOT, "%.1f", v);
    }

    private static String title(String parcelName, AppProperties.Crop crop) {
        return "%s (%s)".formatted(parcelName, crop.name());
    }
}
