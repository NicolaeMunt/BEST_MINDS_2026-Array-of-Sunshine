package md.agro.sensors;

import md.agro.sensors.config.AppProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(AppProperties.class)
public class SensorsAlertsApplication {

    public static void main(String[] args) {
        SpringApplication.run(SensorsAlertsApplication.class, args);
    }
}
