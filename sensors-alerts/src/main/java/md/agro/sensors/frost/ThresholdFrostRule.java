package md.agro.sensors.frost;

import java.time.Duration;
import java.time.Instant;
import java.util.List;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.model.Reading;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class ThresholdFrostRule implements FrostRule {

    private static final Duration WINDOW = Duration.ofHours(1);
    // "Still falling" = within this many degrees of the coldest reading in the window.
    private static final double NEAR_MIN_C = 0.3;

    private final AppProperties.Frost cfg;

    @Autowired
    public ThresholdFrostRule(AppProperties props) {
        this(props.frost());
    }

    public ThresholdFrostRule(AppProperties.Frost cfg) {
        this.cfg = cfg;
    }

    @Override
    public FrostAssessment evaluate(Reading current, List<Reading> history) {
        double temp = current.temperatureC();
        Instant from = current.timestamp().minus(WINDOW);

        // Window is measured in reading timestamps, so it is a simulated hour during replay.
        Double oldest = null;
        double min = temp;
        for (Reading r : history) {
            if (r.timestamp().isBefore(from) || r.timestamp().isAfter(current.timestamp())) {
                continue;
            }
            if (oldest == null) {
                oldest = r.temperatureC();
            }
            min = Math.min(min, r.temperatureC());
        }
        double drop = oldest == null ? 0 : oldest - temp;
        boolean fallingFast = temp < cfg.fallingBelowC()
                && drop > cfg.fallingDropC()
                && temp <= min + NEAR_MIN_C;

        FrostLevel level;
        if (temp <= cfg.criticalTempC()) {
            level = FrostLevel.CRITICAL;
        } else if (temp <= cfg.warningTempC() || fallingFast) {
            level = FrostLevel.WARNING;
        } else {
            level = FrostLevel.OK;
        }
        return new FrostAssessment(level, dewPoint(temp, current.humidityPct()), drop);
    }

    /** Magnus formula. */
    public static double dewPoint(double temperatureC, double humidityPct) {
        double b = 17.62;
        double c = 243.12;
        double rh = Math.max(1, Math.min(100, humidityPct));
        double gamma = Math.log(rh / 100.0) + b * temperatureC / (c + temperatureC);
        return c * gamma / (b - gamma);
    }
}
