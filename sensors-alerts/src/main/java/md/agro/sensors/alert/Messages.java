package md.agro.sensors.alert;

import java.util.Locale;

import md.agro.sensors.frost.FrostAssessment;
import md.agro.sensors.frost.FrostLevel;
import md.agro.sensors.model.Reading;

/** Romanian texts sent to the farmer. */
public final class Messages {

    private Messages() {
    }

    public static String alert(String parcelName, Reading r, FrostAssessment a) {
        return switch (a.level()) {
            case CRITICAL -> "❄️ ÎNGHEȚ – %s\nTemperatura: %s °C\nLuați măsuri imediat."
                    .formatted(parcelName, num(r.temperatureC()));
            case WARNING -> ("⚠️ Risc de îngheț – %s\nTemperatura: %s °C%s\n"
                    + "Umiditate: %.0f%% · Punct de rouă: %s °C\nPregătiți măsurile de protecție.")
                    .formatted(parcelName, num(r.temperatureC()), a.falling() ? " (în scădere)" : "",
                            r.humidityPct(), num(a.dewPointC()));
            case OK -> allClear(parcelName, r);
        };
    }

    public static String allClear(String parcelName, Reading r) {
        return "✅ Pericol trecut – %s\nTemperatura: %s °C".formatted(parcelName, num(r.temperatureC()));
    }

    public static String status(FrostLevel level) {
        return switch (level) {
            case OK -> "✅ OK";
            case WARNING -> "⚠️ Risc de îngheț";
            case CRITICAL -> "❄️ Îngheț";
        };
    }

    public static String num(double v) {
        return String.format(Locale.ROOT, "%.1f", v);
    }
}
