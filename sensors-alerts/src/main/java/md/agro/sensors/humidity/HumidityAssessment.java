package md.agro.sensors.humidity;

/**
 * @param dampHours   HIGH: damp hours counted by the condition that matched; 0 otherwise
 * @param withinHours HIGH: the hours that condition looks back over; 0 otherwise
 */
public record HumidityAssessment(HumidityLevel level, int dampHours, int withinHours) {

    public static final HumidityAssessment OK = new HumidityAssessment(HumidityLevel.OK, 0, 0);
    public static final HumidityAssessment DRY = new HumidityAssessment(HumidityLevel.LOW, 0, 0);
}
