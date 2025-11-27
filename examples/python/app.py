"""
Python SDK Example - Chat with Bot API

This example demonstrates how to interact with the bot API using Python.
It shows basic authentication, message sending, and response handling.

Requirements:
    pip install requests
"""

import requests
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = "http://localhost:8000"  # Updated to new microservice endpoint
API_KEY = "your-api-key-here"  # Replace with your actual API key
BOT_ID = "your-bot-id"  # Replace with your bot ID

# Headers with authentication
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "X-Bot-ID": BOT_ID,
}


class BotClient:
    """Client for interacting with the bot API."""

    def __init__(self, base_url: str, api_key: str, bot_id: str):
        """
        Initialize the bot client.

        Args:
            base_url: Base URL of the bot API
            api_key: API key for authentication
            bot_id: ID of the bot to interact with
        """
        self.base_url = base_url
        self.api_key = api_key
        self.bot_id = bot_id
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Bot-ID": bot_id,
        }
        self.session_id = None

    def start_conversation(self) -> Dict[str, Any]:
        """
        Start a new conversation with the bot.

        Returns:
            Response from the API containing initial bot message
        """
        url = f"{self.base_url}/api/v2/conversations"
        payload = {"bot_id": self.bot_id}

        try:
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            self.session_id = data.get("session_id")
            logger.info(f"Conversation started with session: {self.session_id}")
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to start conversation: {e}")
            raise

    def send_message(self, user_input: str) -> Dict[str, Any]:
        """
        Send a message to the bot.

        Args:
            user_input: User's message

        Returns:
            Response from the API containing bot's response
        """
        if not self.session_id:
            raise ValueError("No active session. Call start_conversation() first.")

        url = f"{self.base_url}/api/v2/conversations/{self.session_id}/messages"
        payload = {"message": user_input}

        try:
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send message: {e}")
            raise

    def get_conversation_history(self) -> Dict[str, Any]:
        """
        Get the conversation history.

        Returns:
            Conversation history from the API
        """
        if not self.session_id:
            raise ValueError("No active session. Call start_conversation() first.")

        url = f"{self.base_url}/api/v2/conversations/{self.session_id}"

        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get conversation history: {e}")
            raise


def main():
    """Main function to run the interactive chat example."""
    logging.basicConfig(level=logging.INFO)

    # Initialize the bot client
    client = BotClient(API_BASE_URL, API_KEY, BOT_ID)

    try:
        # Start a new conversation
        initial_response = client.start_conversation()
        print(f"Bot: {initial_response.get('message', 'Welcome!')}\n")

        # Interactive chat loop
        while True:
            user_input = input("You: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit", "bye"]:
                print("Bot: Goodbye!")
                break

            # Send message and get response
            response = client.send_message(user_input)
            bot_message = response.get("message", "")
            print(f"Bot: {bot_message}\n")

    except KeyboardInterrupt:
        print("\nConversation ended.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()