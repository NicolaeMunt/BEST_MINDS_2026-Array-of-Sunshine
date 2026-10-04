package md.agro.sensors.alert;

import java.util.Locale;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.frost.FrostAssessment;
import md.agro.sensors.frost.FrostLevel;
import md.agro.sensors.humidity.HumidityAssessment;
import md.agro.sensors.humidity.HumidityLevel;
import md.agro.sensors.model.AlertType;
import md.agro.sensors.model.Reading;

/** Romanian texts sent to the farmer. */
public final class Messages {

    private Messages() {
    }

    public static String frost(String parcelName, AppProperties.Crop crop, AppProperties.Phase phase, Reading r,
            FrostAssessment a) {
        String title = title(parcelName, crop);
        return switch (a.level()) {
            case CRITICAL -> "❄️ ÎNGHEȚ – %s\nTemperatura: %s °C (prag critic în faza „%s”: %s °C)\n%s"
                    .formatted(title, num(r.temperatureC()), phase.name(), num(phase.frostCriticalC()),
                            phase.frostAdvice(crop));
            case WARNING -> "⚠️ Risc de îngheț – %s\nTemperatura: %s °C%s (faza „%s”, prag critic %s °C)\nUmiditate: %.0f%% · Punct de rouă: %s °C\n%s"
                    .formatted(title, num(r.temperatureC()), a.falling() ? " (în scădere)" : "", phase.name(),
                            num(phase.frostCriticalC()), r.humidityPct(), num(a.dewPointC()), phase.frostAdvice(crop));
            case OK -> frostAllClear(parcelName, crop, r);
        };
    }

    public static String frostAllClear(String parcelName, AppProperties.Crop crop, Reading r) {
        return "✅ Pericol trecut – %s\nTemperatura: %s °C".formatted(title(parcelName, crop), num(r.temperatureC()));
    }

    public static String humidity(String parcelName, AppProperties.Crop crop, Reading r, HumidityAssessment h) {
        if (h.level() == HumidityLevel.HIGH) {
            AppProperties.Disease d = crop.disease();
            return "🍄 Risc de %s – %s\nAer umed (%.0f%% sau mai mult) %d din ultimele %d ore · acum %.0f%%, %s °C\n%s"
                    .formatted(d.name(), title(parcelName, crop), d.minHumidityPct(), h.dampHours(), h.withinHours(),
                            r.humidityPct(), num(r.temperatureC()), d.advice());
        }
        return "🌵 Aer fierbinte și uscat – %s\nUmiditate: %.0f%% · Temperatura: %s °C\n%s".formatted(
                title(parcelName, crop), r.humidityPct(), num(r.temperatureC()), crop.dry().advice());
    }

    public static String humidityAllClear(String parcelName, AppProperties.Crop crop, Reading r, AlertType type) {
        if (type == AlertType.HUMIDITY_HIGH) {
            return "✅ Riscul de %s a trecut – %s\nUmiditate: %.0f%% · Temperatura: %s °C".formatted(
                    crop.disease() != null ? crop.disease().name() : "boală", title(parcelName, crop), r.humidityPct(),
                    num(r.temperatureC()));
        }
        return "✅ A trecut perioada de aer fierbinte și uscat – %s\nUmiditate: %.0f%% · Temperatura: %s °C".formatted(
                title(parcelName, crop), r.humidityPct(), num(r.temperatureC()));
    }

    /** The phase and what it means for frost, e.g. for the Telegram status. */
    public static String phase(AppProperties.Phase phase) {
        String frost = phase.frostHarms()
                ? "îngheț: avertizare la %s °C, critic la %s °C".formatted(num(phase.frostWarningC()), num(phase.frostCriticalC()))
                : "înghețul nu dăunează acum";
        return "Faza: %s · %s".formatted(phase.name(), frost);
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
            case OK -> "fără risc";
            case LOW -> "🌵 aer fierbinte și uscat";
            case HIGH -> "🍄 risc de boală";
        };
    }

    public static String num(double v) {
        return String.format(Locale.ROOT, "%.1f", v);
    }

    private static String title(String parcelName, AppProperties.Crop crop) {
        return "%s (%s)".formatted(parcelName, crop.name());
    }
}
