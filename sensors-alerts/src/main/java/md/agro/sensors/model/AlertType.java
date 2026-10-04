package md.agro.sensors.model;

public enum AlertType {
    FROST, HUMIDITY_HIGH, HUMIDITY_LOW,
    /** From the backend's soil water advice; this service only stores and sends it. */
    IRRIGATION,
    /** From the backend: the soil is warm enough to sow; this service only stores and sends it. */
    SOWING
}
