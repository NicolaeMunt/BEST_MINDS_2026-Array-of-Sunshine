package md.agro.sensors.alert;

import md.agro.sensors.model.Alert;

public interface AlertNotifier {

    /** Must not throw and must not block the caller. */
    void send(Alert alert);
}
