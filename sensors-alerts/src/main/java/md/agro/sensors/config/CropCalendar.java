package md.agro.sensors.config;

import java.time.Instant;
import java.time.LocalDate;
import java.time.MonthDay;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
import java.time.temporal.ChronoUnit;
import java.util.List;

/** Which phase a crop is in, and whether a day falls inside a month-day window, on Chișinău local days. */
public final class CropCalendar {

    public static final ZoneId ZONE = ZoneId.of("Europe/Chisinau");

    private static final AppProperties.Phase NO_PHASE = new AppProperties.Phase("01-01", "", "growing", null, null, null, null);

    /** A sowing date further than this from the calendar's is taken as a typing mistake and ignored. */
    static final int MAX_SHIFT_DAYS = 60;

    private CropCalendar() {
    }

    /**
     * The crop's rules for a parcel sown on {@code sowingDate}: every phase, the disease window and the dry window
     * move by the days between the calendar's sowing day and the farmer's. Unchanged for a crop without
     * calendarSowing, without a sowing date, or with a date more than MAX_SHIFT_DAYS off.
     */
    public static AppProperties.Crop forSowing(AppProperties.Crop crop, String sowingDate) {
        if (crop.calendarSowing() == null || sowingDate == null || sowingDate.isBlank()) {
            return crop;
        }
        LocalDate sown;
        try {
            sown = LocalDate.parse(sowingDate.trim());
        } catch (DateTimeParseException e) {
            return crop;
        }
        long days = ChronoUnit.DAYS.between(monthDay(crop.calendarSowing()).atYear(sown.getYear()), sown);
        if (days == 0 || Math.abs(days) > MAX_SHIFT_DAYS) {
            return crop;
        }
        List<AppProperties.Phase> phases = crop.phases().stream()
                .map(p -> new AppProperties.Phase(shift(p.from(), days), p.name(), p.season(), p.frostWarningC(),
                        p.frostCriticalC(), p.kc(), p.frostAdvice()))
                .sorted((a, b) -> monthDay(a.from()).compareTo(monthDay(b.from())))
                .toList();
        AppProperties.Disease d = crop.disease();
        AppProperties.Disease disease = d == null ? null : new AppProperties.Disease(d.name(), shift(d.from(), days),
                shift(d.to(), days), d.minHumidityPct(), d.conditions(), d.advice());
        AppProperties.Window w = crop.dry();
        AppProperties.Window dry = w == null ? null : new AppProperties.Window(shift(w.from(), days), shift(w.to(), days), w.advice());
        return new AppProperties.Crop(crop.name(), crop.frostAdvice(), phases, disease, dry, crop.calendarSowing());
    }

    /** A month-day moved by some days, within the year (01-01 stays the first day). */
    private static String shift(String monthDay, long days) {
        LocalDate d = monthDay(monthDay).atYear(2026);
        LocalDate moved = d.plusDays(days);
        if (moved.getYear() != d.getYear()) {
            moved = days < 0 ? d.withDayOfYear(1) : d.withMonth(12).withDayOfMonth(31);
        }
        if (monthDay.trim().equals("01-01")) {
            moved = d;  // the phase that starts the year keeps covering the days before the first shifted phase
        }
        return "%02d-%02d".formatted(moved.getMonthValue(), moved.getDayOfMonth());
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
