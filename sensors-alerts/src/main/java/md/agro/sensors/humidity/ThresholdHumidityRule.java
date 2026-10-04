package md.agro.sensors.humidity;

import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.config.CropCalendar;
import md.agro.sensors.model.Reading;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/**
 * HIGH: the crop's disease window is open and, within the last holdHours, the air was damp long enough for one
 * of the disease's conditions (wet leaves let the fungus in).
 * LOW: the crop's dry window is open and the air was dry and hot (suhovei) within the last holdHours.
 * Hours are clock hours of the reading timestamps, so they are simulated hours during a replay.
 */
@Component
public class ThresholdHumidityRule implements HumidityRule {

    private final AppProperties.Humidity cfg;

    @Autowired
    public ThresholdHumidityRule(AppProperties props) {
        this(props.humidity());
    }

    public ThresholdHumidityRule(AppProperties.Humidity cfg) {
        this.cfg = cfg;
    }

    @Override
    public HumidityAssessment evaluate(Reading current, List<Reading> history, AppProperties.Crop crop) {
        Instant now = current.timestamp();
        AppProperties.Disease disease = crop.disease();
        if (disease != null && CropCalendar.within(disease.from(), disease.to(), now)) {
            Map<Instant, double[]> hours = hourlyMeans(current, history);
            Instant thisHour = now.truncatedTo(ChronoUnit.HOURS);
            // The newest hour at which a condition was met, looking back holdHours.
            for (int back = 0; back <= cfg.holdHours(); back++) {
                Instant end = thisHour.minus(back, ChronoUnit.HOURS);
                for (AppProperties.Condition c : disease.conditions()) {
                    int damp = dampHours(hours, end, c, disease.minHumidityPct());
                    if (damp >= c.hours()) {
                        return new HumidityAssessment(HumidityLevel.HIGH, damp, c.withinHours());
                    }
                }
            }
        }
        AppProperties.Window dry = crop.dry();
        if (dry != null && CropCalendar.within(dry.from(), dry.to(), now)) {
            Instant from = now.minus(Duration.ofHours(cfg.holdHours()));
            boolean dryAir = isDry(current) || history.stream()
                    .anyMatch(r -> !r.timestamp().isBefore(from) && !r.timestamp().isAfter(now) && isDry(r));
            if (dryAir) {
                return HumidityAssessment.DRY;
            }
        }
        return HumidityAssessment.OK;
    }

    /** Damp hours at the condition's temperatures among the withinHours ending with {@code end}. */
    private static int dampHours(Map<Instant, double[]> hours, Instant end, AppProperties.Condition c, double minHumidityPct) {
        int damp = 0;
        for (int i = 0; i < c.withinHours(); i++) {
            double[] h = hours.get(end.minus(i, ChronoUnit.HOURS));
            if (h != null && h[1] >= minHumidityPct && h[0] >= c.minTempC() && h[0] <= c.maxTempC()) {
                damp++;
            }
        }
        return damp;
    }

    private boolean isDry(Reading r) {
        return r.humidityPct() <= cfg.dryMaxPct() && r.temperatureC() >= cfg.dryMinTempC();
    }

    /** Clock hour -> {mean temperature, mean humidity} of the readings in it, up to {@code current}. */
    private static Map<Instant, double[]> hourlyMeans(Reading current, List<Reading> history) {
        Map<Instant, double[]> sums = new HashMap<>();
        for (Reading r : history) {
            if (!r.timestamp().isAfter(current.timestamp())) {
                add(sums, r);
            }
        }
        add(sums, current);
        Map<Instant, double[]> means = new HashMap<>();
        sums.forEach((hour, s) -> means.put(hour, new double[] {s[0] / s[2], s[1] / s[2]}));
        return means;
    }

    private static void add(Map<Instant, double[]> sums, Reading r) {
        double[] s = sums.computeIfAbsent(r.timestamp().truncatedTo(ChronoUnit.HOURS), k -> new double[3]);
        s[0] += r.temperatureC();
        s[1] += r.humidityPct();
        s[2]++;
    }
}
