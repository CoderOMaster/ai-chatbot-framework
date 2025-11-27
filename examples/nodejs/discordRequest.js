/**
 * Discord Bot Integration Example
 *
 * This module demonstrates how to integrate a Discord bot with the chat API.
 * It handles authentication, message sending, and response handling.
 *
 * Requirements:
 *   npm install discord.js axios
 *
 * Setup:
 *   1. Set environment variables:
 *      - BOT_API_KEY: Your API key for authentication
 *      - BOT_ID: The ID of your bot
 *      - API_BASE_URL: Base URL of the bot API (default: http://localhost:8000)
 */

const axios = require('axios');

// Configuration
const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8000';
const API_KEY = process.env.BOT_API_KEY || 'your-api-key-here';
const BOT_ID = process.env.BOT_ID || 'your-bot-id';

// Create axios instance with default headers
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${API_KEY}`,
    'X-Bot-ID': BOT_ID,
  },
});

/**
 * BotClient class for managing conversations with the bot API
 */
class BotClient {
  constructor(apiKey, botId, baseUrl = API_BASE_URL) {
    this.apiKey = apiKey;
    this.botId = botId;
    this.baseUrl = baseUrl;
    this.sessionId = null;
  }

  /**
   * Start a new conversation with the bot
   * @returns {Promise<Object>} Response containing session_id and initial message
   */
  async startConversation() {
    try {
      const response = await apiClient.post('/api/v2/conversations', {
        bot_id: this.botId,
      });
      this.sessionId = response.data.session_id;
      console.log(`Conversation started with session: ${this.sessionId}`);
      return response.data;
    } catch (error) {
      console.error('Failed to start conversation:', error.message);
      throw error;
    }
  }

  /**
   * Send a message to the bot
   * @param {string} userMessage - The user's message
   * @returns {Promise<Object>} Response containing bot's message
   */
  async sendMessage(userMessage) {
    if (!this.sessionId) {
      throw new Error('No active session. Call startConversation() first.');
    }

    try {
      const response = await apiClient.post(
        `/api/v2/conversations/${this.sessionId}/messages`,
        { message: userMessage }
      );
      return response.data;
    } catch (error) {
      console.error('Failed to send message:', error.message);
      throw error;
    }
  }

  /**
   * Get conversation history
   * @returns {Promise<Object>} Conversation history
   */
  async getConversationHistory() {
    if (!this.sessionId) {
      throw new Error('No active session. Call startConversation() first.');
    }

    try {
      const response = await apiClient.get(
        `/api/v2/conversations/${this.sessionId}`
      );
      return response.data;
    } catch (error) {
      console.error('Failed to get conversation history:', error.message);
      throw error;
    }
  }
}

/**
 * Discord integration module
 * Handles incoming Discord messages and sends them to the bot API
 */
module.exports = {
  /**
   * Handle a Discord message and send it to the bot API
   * @param {Object} msg - Discord message object from discord.js
   * @param {BotClient} botClient - Instance of BotClient
   */
  chatRequest: async function (msg, botClient) {
    try {
      // Skip bot messages
      if (msg.author.bot) {
        return;
      }

      // Get the clean user input
      const userInput = msg.cleanContent.trim();

      if (!userInput) {
        return;
      }

      // Show typing indicator
      await msg.channel.sendTyping();

      // Send message to bot API
      const response = await botClient.sendMessage(userInput);
      const botMessage = response.message || 'I did not understand that.';

      // Send response to Discord channel
      await msg.reply({
        content: botMessage,
        allowedMentions: { repliedUser: false },
      });
    } catch (error) {
      console.error('Error processing message:', error);
      await msg.reply({
        content: 'Sorry, I encountered an error processing your message.',
        allowedMentions: { repliedUser: false },
      });
    }
  },

  /**
   * Initialize bot client for Discord integration
   * @returns {BotClient} Initialized bot client
   */
  initializeBotClient: function () {
    return new BotClient(API_KEY, BOT_ID, API_BASE_URL);
  },

  /**
   * BotClient class export for direct usage
   */
  BotClient: BotClient,
};

/**
 * Example usage in a Discord bot:
 *
 * const Discord = require('discord.js');
 * const botIntegration = require('./discordRequest');
 *
 * const client = new Discord.Client();
 * const botClient = botIntegration.initializeBotClient();
 *
 * client.on('ready', async () => {
 *   console.log(`Logged in as ${client.user.tag}`);
 *   await botClient.startConversation();
 * });
 *
 * client.on('messageCreate', async (msg) => {
 *   await botIntegration.chatRequest(msg, botClient);
 * });
 *
 * client.login(process.env.DISCORD_TOKEN);
 */