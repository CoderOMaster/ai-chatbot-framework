package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"bufio"
	"strings"
)

// Configuration
const (
	defaultAPIURL = "http://localhost:8000"
)

// BotClient handles communication with the bot API
type BotClient struct {
	baseURL   string
	apiKey    string
	botID     string
	sessionID string
	client    *http.Client
}

// ConversationRequest represents the request to start a conversation
type ConversationRequest struct {
	BotID string `json:"bot_id"`
}

// ConversationResponse represents the response from starting a conversation
type ConversationResponse struct {
	SessionID string `json:"session_id"`
	Message   string `json:"message"`
}

// MessageRequest represents a message to send to the bot
type MessageRequest struct {
	Message string `json:"message"`
}

// MessageResponse represents the response from sending a message
type MessageResponse struct {
	Message    string  `json:"message"`
	Intent     string  `json:"intent"`
	Confidence float64 `json:"confidence"`
}

// NewBotClient creates a new bot client
func NewBotClient(baseURL, apiKey, botID string) *BotClient {
	if baseURL == "" {
		baseURL = defaultAPIURL
	}
	return &BotClient{
		baseURL: baseURL,
		apiKey:  apiKey,
		botID:   botID,
		client:  &http.Client{},
	}
}

// StartConversation starts a new conversation with the bot
func (bc *BotClient) StartConversation() error {
	url := fmt.Sprintf("%s/api/v2/conversations", bc.baseURL)
	
	reqBody := ConversationRequest{
		BotID: bc.botID,
	}
	
	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	bc.setHeaders(req)

	resp, err := bc.client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("unexpected status code: %d, body: %s", resp.StatusCode, string(body))
	}

	var respBody ConversationResponse
	if err := json.NewDecoder(resp.Body).Decode(&respBody); err != nil {
		return fmt.Errorf("failed to decode response: %w", err)
	}

	bc.sessionID = respBody.SessionID
	fmt.Printf("Bot: %s\n\n", respBody.Message)
	return nil
}

// SendMessage sends a message to the bot
func (bc *BotClient) SendMessage(message string) error {
	if bc.sessionID == "" {
		return fmt.Errorf("no active session, call StartConversation first")
	}

	url := fmt.Sprintf("%s/api/v2/conversations/%s/messages", bc.baseURL, bc.sessionID)
	
	reqBody := MessageRequest{
		Message: message,
	}
	
	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	bc.setHeaders(req)

	resp, err := bc.client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("unexpected status code: %d, body: %s", resp.StatusCode, string(body))
	}

	var respBody MessageResponse
	if err := json.NewDecoder(resp.Body).Decode(&respBody); err != nil {
		return fmt.Errorf("failed to decode response: %w", err)
	}

	fmt.Printf("Bot: %s\n\n", respBody.Message)
	return nil
}

// setHeaders sets the required headers for API requests
func (bc *BotClient) setHeaders(req *http.Request) {
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", bc.apiKey))
	req.Header.Set("X-Bot-ID", bc.botID)
}

func main() {
	// Get configuration from environment variables
	apiKey := os.Getenv("BOT_API_KEY")
	if apiKey == "" {
		apiKey = "your-api-key-here"
	}

	botID := os.Getenv("BOT_ID")
	if botID == "" {
		botID = "your-bot-id"
	}

	apiURL := os.Getenv("API_BASE_URL")
	if apiURL == "" {
		apiURL = defaultAPIURL
	}

	// Create bot client
	client := NewBotClient(apiURL, apiKey, botID)

	// Start conversation
	if err := client.StartConversation(); err != nil {
		log.Fatalf("Failed to start conversation: %v", err)
	}

	// Interactive chat loop
	scanner := bufio.NewScanner(os.Stdin)
	fmt.Print("You: ")

	for scanner.Scan() {
		input := strings.TrimSpace(scanner.Text())

		if input == "" {
			fmt.Print("You: ")
			continue
		}

		if strings.ToLower(input) == "exit" || strings.ToLower(input) == "quit" {
			fmt.Println("Bot: Goodbye!")
			break
		}

		if err := client.SendMessage(input); err != nil {
			log.Printf("Error sending message: %v", err)
		}

		fmt.Print("You: ")
	}

	if err := scanner.Err(); err != nil {
		log.Fatalf("Scanner error: %v", err)
	}
}