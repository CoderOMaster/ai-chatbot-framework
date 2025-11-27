import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Scanner;
import com.google.gson.Gson;
import com.google.gson.JsonObject;

/**
 * Java SDK Example - Chat with Bot API
 *
 * This example demonstrates how to interact with the bot API using Java.
 * It shows authentication, message sending, and response handling.
 *
 * Requirements:
 *   - Java 11+
 *   - Gson library (com.google.code.gson:gson)
 *
 * Maven dependency:
 *   <dependency>
 *       <groupId>com.google.code.gson</groupId>
 *       <artifactId>gson</artifactId>
 *       <version>2.10.1</version>
 *   </dependency>
 */
public class BotClient {
    private static final String DEFAULT_API_URL = "http://localhost:8000";
    private static final String API_VERSION = "/api/v2";

    private final String baseUrl;
    private final String apiKey;
    private final String botId;
    private final HttpClient httpClient;
    private final Gson gson;
    private String sessionId;

    /**
     * Initialize the bot client.
     *
     * @param baseUrl Base URL of the bot API
     * @param apiKey API key for authentication
     * @param botId ID of the bot to interact with
     */
    public BotClient(String baseUrl, String apiKey, String botId) {
        this.baseUrl = baseUrl != null ? baseUrl : DEFAULT_API_URL;
        this.apiKey = apiKey;
        this.botId = botId;
        this.httpClient = HttpClient.newHttpClient();
        this.gson = new Gson();
    }

    /**
     * Start a new conversation with the bot.
     *
     * @return Response containing session_id and initial message
     * @throws IOException if an I/O error occurs
     * @throws InterruptedException if the request is interrupted
     */
    public JsonObject startConversation() throws IOException, InterruptedException {
        String url = baseUrl + API_VERSION + "/conversations";

        JsonObject requestBody = new JsonObject();
        requestBody.addProperty("bot_id", botId);

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Content-Type", "application/json")
                .header("Authorization", "Bearer " + apiKey)
                .header("X-Bot-ID", botId)
                .POST(HttpRequest.BodyPublishers.ofString(gson.toJson(requestBody)))
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());

        if (response.statusCode() != 200 && response.statusCode() != 201) {
            throw new RuntimeException("Failed to start conversation: " + response.statusCode() + " " + response.body());
        }

        JsonObject responseBody = gson.fromJson(response.body(), JsonObject.class);
        this.sessionId = responseBody.get("session_id").getAsString();
        System.out.println("Conversation started with session: " + sessionId);

        return responseBody;
    }

    /**
     * Send a message to the bot.
     *
     * @param userMessage The user's message
     * @return Response containing bot's message
     * @throws IOException if an I/O error occurs
     * @throws InterruptedException if the request is interrupted
     */
    public JsonObject sendMessage(String userMessage) throws IOException, InterruptedException {
        if (sessionId == null || sessionId.isEmpty()) {
            throw new IllegalStateException("No active session. Call startConversation() first.");
        }

        String url = baseUrl + API_VERSION + "/conversations/" + sessionId + "/messages";

        JsonObject requestBody = new JsonObject();
        requestBody.addProperty("message", userMessage);

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Content-Type", "application/json")
                .header("Authorization", "Bearer " + apiKey)
                .header("X-Bot-ID", botId)
                .POST(HttpRequest.BodyPublishers.ofString(gson.toJson(requestBody)))
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());

        if (response.statusCode() != 200) {
            throw new RuntimeException("Failed to send message: " + response.statusCode() + " " + response.body());
        }

        return gson.fromJson(response.body(), JsonObject.class);
    }

    /**
     * Get conversation history.
     *
     * @return Conversation history
     * @throws IOException if an I/O error occurs
     * @throws InterruptedException if the request is interrupted
     */
    public JsonObject getConversationHistory() throws IOException, InterruptedException {
        if (sessionId == null || sessionId.isEmpty()) {
            throw new IllegalStateException("No active session. Call startConversation() first.");
        }

        String url = baseUrl + API_VERSION + "/conversations/" + sessionId;

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Authorization", "Bearer " + apiKey)
                .header("X-Bot-ID", botId)
                .GET()
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());

        if (response.statusCode() != 200) {
            throw new RuntimeException("Failed to get conversation history: " + response.statusCode() + " " + response.body());
        }

        return gson.fromJson(response.body(), JsonObject.class);
    }

    /**
     * Main method to run the interactive chat example.
     */
    public static void main(String[] args) {
        String apiKey = System.getenv("BOT_API_KEY");
        if (apiKey == null) {
            apiKey = "your-api-key-here";
        }

        String botId = System.getenv("BOT_ID");
        if (botId == null) {
            botId = "your-bot-id";
        }

        String apiUrl = System.getenv("API_BASE_URL");
        if (apiUrl == null) {
            apiUrl = DEFAULT_API_URL;
        }

        BotClient client = new BotClient(apiUrl, apiKey, botId);

        try {
            // Start conversation
            JsonObject initialResponse = client.startConversation();
            String initialMessage = initialResponse.has("message") ? initialResponse.get("message").getAsString() : "Welcome!";
            System.out.println("Bot: " + initialMessage + "\n");

            // Interactive chat loop
            Scanner scanner = new Scanner(System.in);
            while (true) {
                System.out.print("You: ");
                String userInput = scanner.nextLine().trim();

                if (userInput.isEmpty()) {
                    continue;
                }

                if (userInput.equalsIgnoreCase("exit") || userInput.equalsIgnoreCase("quit")) {
                    System.out.println("Bot: Goodbye!");
                    break;
                }

                JsonObject response = client.sendMessage(userInput);
                String botMessage = response.has("message") ? response.get("message").getAsString() : "I did not understand that.";
                System.out.println("Bot: " + botMessage + "\n");
            }

            scanner.close();
        } catch (IOException | InterruptedException e) {
            System.err.println("Error: " + e.getMessage());
            e.printStackTrace();
        }
    }
}