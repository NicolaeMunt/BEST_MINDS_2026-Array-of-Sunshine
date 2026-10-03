package md.agro.sensors.frost;

/**
 * @param dropLastHourC how much colder it is now than at the start of the last (simulated) hour;
 *                      negative when it is warming up
 */
public record FrostAssessment(FrostLevel level, double dewPointC, double dropLastHourC) {

    public boolean falling() {
        return dropLastHourC > 0.3;
    }
}
