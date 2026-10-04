package md.agro.sensors.sim;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.Resource;

/** Loads a replay CSV: timestamp,temperatureC,humidityPct and optionally precipitationMm. */
final class ReplayData {

    private static final Logger log = LoggerFactory.getLogger(ReplayData.class);

    record Row(Instant timestamp, double temperatureC, double humidityPct, double precipitationMm) {
    }

    private ReplayData() {
    }

    /** Lines that cannot be parsed (header, comments, blanks) are skipped. Comma or semicolon separated. */
    static List<Row> load(Resource resource, ZoneId zone) throws IOException {
        List<Row> rows = new ArrayList<>();
        try (BufferedReader in = new BufferedReader(
                new InputStreamReader(resource.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            int n = 0;
            while ((line = in.readLine()) != null) {
                n++;
                String clean = line.replace("﻿", "").trim();
                if (clean.startsWith("#")) {
                    continue;
                }
                String[] p = clean.split("[,;]");
                if (p.length < 3) {
                    continue;
                }
                try {
                    rows.add(new Row(parseTime(p[0].trim(), zone), Double.parseDouble(p[1].trim()),
                            Double.parseDouble(p[2].trim()), p.length > 3 ? Double.parseDouble(p[3].trim()) : 0));
                } catch (DateTimeParseException | NumberFormatException e) {
                    // The header is skipped quietly; anything else that does not parse is worth a warning.
                    if (!Character.isLetter(clean.charAt(0))) {
                        log.warn("Replay CSV line {} skipped: {}", n, line);
                    }
                }
            }
        }
        return rows;
    }

    /** Accepts 2025-04-08T18:00, 2025-04-08 18:00[:00], and ISO with offset or Z. */
    private static Instant parseTime(String s, ZoneId zone) {
        String iso = s.replace(' ', 'T');
        try {
            return OffsetDateTime.parse(iso).toInstant();
        } catch (DateTimeParseException e) {
            return LocalDateTime.parse(iso).atZone(zone).toInstant();
        }
    }
}
