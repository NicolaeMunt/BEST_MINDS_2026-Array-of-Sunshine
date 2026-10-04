package md.agro.sensors.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import java.io.IOException;
import java.time.Instant;

import org.junit.jupiter.api.Test;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.core.io.ClassPathResource;

/** The real application.yml binds to AppProperties: the crop rules are read the way the app reads them. */
class ConfigBindingTest {

    @Test
    void applicationYmlBinds() throws IOException {
        StandardEnvironment env = new StandardEnvironment();
        new YamlPropertySourceLoader().load("app", new ClassPathResource("application.yml"))
                .forEach(env.getPropertySources()::addLast);
        // Binder.get resolves the ${...} placeholders the way the app does.
        AppProperties props = Binder.get(env).bind("app", AppProperties.class).get();

        assertEquals(5, props.parcels().size());
        AppProperties.Crop corn = props.crops().get("corn");
        assertEquals("04-20", corn.calendarSowing());
        assertNotNull(corn.disease());
        assertEquals("helmintosporioză", corn.disease().name());
        assertEquals(-2.0, CropCalendar.phase(corn, Instant.parse("2026-05-10T00:00:00Z")).frostCriticalC());
        assertEquals("rapăn", props.crops().get("orchard").disease().name());
        assertEquals(24, props.humidity().holdHours());
    }
}
