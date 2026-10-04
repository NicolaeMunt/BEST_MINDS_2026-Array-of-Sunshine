package md.agro.sensors.telegram;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import jakarta.annotation.PreDestroy;
import md.agro.sensors.alert.AlertNotifier;
import md.agro.sensors.alert.Messages;
import md.agro.sensors.config.AppProperties;
import md.agro.sensors.config.CropCalendar;
import md.agro.sensors.model.Alert;
import md.agro.sensors.model.Reading;
import md.agro.sensors.store.ParcelRegistry;
import md.agro.sensors.store.SensorStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import org.telegram.telegrambots.bots.TelegramLongPollingBot;
import org.telegram.telegrambots.meta.TelegramBotsApi;
import org.telegram.telegrambots.meta.api.methods.send.SendMessage;
import org.telegram.telegrambots.meta.api.objects.Update;
import org.telegram.telegrambots.updatesreceivers.DefaultBotSession;

/** Long-polling bot. Without a token the app still runs and alerts are only logged. */
@Component
public class TelegramNotifier implements AlertNotifier {

    private static final Logger log = LoggerFactory.getLogger(TelegramNotifier.class);

    private final AppProperties props;
    private final ParcelRegistry parcels;
    private final SensorStore store;
    // Chats that sent /start; also written to chatsFile so they survive restarts.
    private final Set<String> chats = ConcurrentHashMap.newKeySet();
    private final ExecutorService sender = Executors.newSingleThreadExecutor();
    private volatile Bot bot;

    public TelegramNotifier(AppProperties props, ParcelRegistry parcels, SensorStore store) {
        this.props = props;
        this.parcels = parcels;
        this.store = store;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void start() {
        loadChats();
        String token = props.telegram().token().trim();
        if (token.isBlank()) {
            log.warn("TELEGRAM_BOT_TOKEN not set: alerts are logged, not sent");
            return;
        }
        try {
            Bot b = new Bot(token);
            new TelegramBotsApi(DefaultBotSession.class).registerBot(b);
            bot = b;
            log.info("Telegram bot @{} started", b.getBotUsername());
        } catch (Exception e) {
            log.error("Telegram bot could not start; alerts are logged, not sent", e);
        }
    }

    private void loadChats() {
        Path file = Path.of(props.telegram().chatsFile());
        if (!Files.exists(file)) {
            return;
        }
        try {
            Files.readAllLines(file).stream().map(String::trim).filter(s -> !s.isEmpty()).forEach(chats::add);
            log.info("Loaded {} subscribed Telegram chat(s) from {}", chats.size(), file);
        } catch (IOException e) {
            log.warn("Could not read {}: {}", file, e.getMessage());
        }
    }

    private void saveChats() {
        try {
            Files.write(Path.of(props.telegram().chatsFile()), chats);
        } catch (IOException e) {
            log.warn("Could not save subscribed chats: {}", e.getMessage());
        }
    }

    @PreDestroy
    public void stop() {
        sender.shutdownNow();
    }

    @Override
    public void send(Alert alert) {
        Set<String> targets = new LinkedHashSet<>(chats);
        String fallback = props.telegram().fallbackChatId();
        if (!fallback.isBlank()) {
            targets.add(fallback.trim());
        }
        if (bot == null || targets.isEmpty()) {
            log.info("[telegram not sent: {}]\n{}", bot == null ? "bot off" : "no chats", alert.message());
            return;
        }
        sender.submit(() -> targets.forEach(chat -> deliver(chat, alert.message())));
    }

    /** One retry, then give up; never throws. */
    private void deliver(String chatId, String text) {
        Bot b = bot;
        if (b == null) {
            return;
        }
        for (int attempt = 1; attempt <= 2; attempt++) {
            try {
                b.execute(SendMessage.builder().chatId(chatId).text(text).build());
                return;
            } catch (Exception e) {
                log.warn("Telegram send to {} failed (attempt {}): {}", chatId, attempt, e.getMessage());
            }
        }
    }

    private String reply(String chatId, String text) {
        String[] parts = text.trim().split("\\s+");
        // Commands arrive as /start@BotName in groups.
        String command = parts[0].split("@")[0].toLowerCase();
        return switch (command) {
            case "/start" -> {
                chats.add(chatId);
                saveChats();
                yield "Bun venit! Veți primi alerte de îngheț și de umiditate pentru toate parcelele.\n"
                        + "/parcele – lista parcelelor\n/status <parcelId> – detalii parcelă\n"
                        + "Chat ID: " + chatId;
            }
            case "/parcele" -> parcelList();
            case "/status" -> parts.length < 2 ? "Folosire: /status <parcelId>" : status(parts[1]);
            default -> "Comenzi: /start, /parcele, /status <parcelId>";
        };
    }

    private String parcelList() {
        StringBuilder sb = new StringBuilder("Parcele:\n");
        for (AppProperties.Parcel p : parcels.all()) {
            sb.append(p.id()).append(" – ").append(p.name())
                    .append(" (").append(parcels.cropFor(p.id()).name()).append("): ");
            Optional<SensorStore.Status> st = store.latest(p.id());
            if (st.isPresent()) {
                sb.append(Messages.num(st.get().reading().temperatureC())).append(" °C · ")
                        .append(Messages.status(st.get().assessment().level()))
                        .append(" · umiditate ").append(Messages.status(st.get().humidity()));
            } else {
                sb.append("fără date");
            }
            sb.append('\n');
        }
        return sb.toString().trim();
    }

    private String status(String parcelId) {
        Optional<AppProperties.Parcel> parcel = parcels.get(parcelId);
        if (parcel.isEmpty()) {
            return "Parcelă necunoscută: " + parcelId;
        }
        Optional<SensorStore.Status> st = store.latest(parcel.get().id());
        if (st.isEmpty()) {
            return parcel.get().name() + ": fără date";
        }
        Reading r = st.get().reading();
        AppProperties.Crop crop = parcels.cropFor(parcel.get().id());
        return "%s (%s) – %s\nTemperatura: %s °C\nUmiditate: %.0f%% (%s)\nPunct de rouă: %s °C\nStare: %s\n%s".formatted(
                parcel.get().name(), parcel.get().id(), crop.name(), Messages.num(r.temperatureC()),
                r.humidityPct(), Messages.status(st.get().humidity()),
                Messages.num(st.get().assessment().dewPointC()), Messages.status(st.get().assessment().level()),
                Messages.phase(CropCalendar.phase(crop, r.timestamp())));
    }

    private final class Bot extends TelegramLongPollingBot {

        Bot(String token) {
            super(token);
        }

        @Override
        public String getBotUsername() {
            // Tolerate "@MyBot" in the config.
            return props.telegram().username().trim().replaceFirst("^@", "");
        }

        @Override
        public void onUpdateReceived(Update update) {
            try {
                if (update.hasMessage() && update.getMessage().hasText()) {
                    String chatId = String.valueOf(update.getMessage().getChatId());
                    log.info("Telegram message from chat {}: {}", chatId, update.getMessage().getText());
                    String answer = reply(chatId, update.getMessage().getText());
                    sender.submit(() -> deliver(chatId, answer));
                }
            } catch (RuntimeException e) {
                log.error("Failed to handle Telegram update", e);
            }
        }
    }
}
