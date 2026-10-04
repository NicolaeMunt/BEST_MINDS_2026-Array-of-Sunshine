package md.agro.sensors.store;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import md.agro.sensors.config.AppProperties;
import md.agro.sensors.config.CropCalendar;
import org.springframework.stereotype.Component;

/**
 * The parcels this service has sensors for. Starts with app.parcels from the config; the backend
 * adds or updates its own parcels at runtime, so both services share one parcel list.
 */
@Component
public class ParcelRegistry {

    private final AppProperties props;
    private final Map<String, AppProperties.Parcel> parcels = new LinkedHashMap<>();

    public ParcelRegistry(AppProperties props) {
        this.props = props;
        props.parcels().forEach(p -> parcels.put(p.id(), p));
    }

    public synchronized List<AppProperties.Parcel> all() {
        return new ArrayList<>(parcels.values());
    }

    /** Exact ID first, then ignoring case (people type "/status p1" in Telegram). */
    public synchronized Optional<AppProperties.Parcel> get(String id) {
        AppProperties.Parcel exact = parcels.get(id);
        if (exact != null) {
            return Optional.of(exact);
        }
        return parcels.values().stream().filter(p -> p.id().equalsIgnoreCase(id)).findFirst();
    }

    /** Adds the parcel or replaces its name, crop and sowing date. */
    public synchronized AppProperties.Parcel put(String id, String name, String crop, String sowingDate) {
        AppProperties.Parcel parcel = new AppProperties.Parcel(id,
                name == null || name.isBlank() ? id : name.trim(), crop == null ? "" : crop.trim(),
                sowingDate == null || sowingDate.isBlank() ? null : sowingDate.trim());
        parcels.put(id, parcel);
        return parcel;
    }

    public String name(String id) {
        return get(id).map(AppProperties.Parcel::name).orElse(id);
    }

    /** Crop key of the parcel, or "" if it has none. */
    public String cropKey(String id) {
        return get(id).map(p -> p.crop().trim().toLowerCase()).orElse("");
    }

    /** The rules of the parcel's crop, moved to the parcel's sowing date when it has one. */
    public AppProperties.Crop cropFor(String id) {
        AppProperties.Crop crop = props.crops().getOrDefault(cropKey(id), AppProperties.DEFAULT_CROP);
        return CropCalendar.forSowing(crop, get(id).map(AppProperties.Parcel::sowingDate).orElse(null));
    }
}
