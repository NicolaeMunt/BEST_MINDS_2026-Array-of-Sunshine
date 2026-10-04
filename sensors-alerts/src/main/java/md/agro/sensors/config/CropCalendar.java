package md.agro.sensors.config;

import java.time.Instant;
import java.time.MonthDay;
import java.time.ZoneId;
import java.util.List;

/** Which phase a crop is in, and whether a day falls inside a month-day window, on Chișinău local days. */
public final class CropCalendar {

    public static final ZoneId ZONE = ZoneId.of("Europe/Chisinau");

    private static final AppProperties.Phase NO_PHASE = new AppProperties.Phase("01-01", "", "growing", null, null, null, null);

    private CropCalendar() {
    }

    /** The phase on the local day of {@code time}. Before the first phase starts, last year's last phase still runs. */
    public static AppProperties.Phase phase(AppProperties.Crop crop, Instant time) {
        List<AppProperties.Phase> phases = crop.phases();
        if (phases.isEmpty()) {
            return NO_PHASE;
        }
        MonthDay day = day(time);
        AppProperties.Phase current = phases.get(phases.size() - 1);
        for (AppProperties.Phase p : phases) {
            if (!monthDay(p.from()).isAfter(day)) {
                current = p;
            }
        }
        return current;
    }

    /** {@code from} and {@code to} are month-days (05-20) and both count. */
    public static boolean within(String from, String to, Instant time) {
        MonthDay day = day(time);
        return !day.isBefore(monthDay(from)) && !day.isAfter(monthDay(to));
    }

    private static MonthDay day(Instant time) {
        return MonthDay.from(time.atZone(ZONE));
    }

    private static MonthDay monthDay(String text) {
        return MonthDay.parse("--" + text.trim());
    }
}
