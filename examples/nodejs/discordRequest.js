/**
 * Discord chatbot request handler
 * Sends user messages to the chatbot API and returns responses to Discord
 */

/**
 * Sends a Discord message to the chatbot API and returns the response
 * @param {Object} msg - Discord.js message object representing a user message
 * @param {string} apiUrl - Base URL of the chatbot API (default: http://localhost:8001)
 */
async function chatRequest(msg, apiUrl = process.env.CHATBOT_API_URL || 'http://localhost:8001') {
  const Discord = require('discord.js');

  const payload = {
    currentNode: '',
    complete: null,
    context: {},
    parameters: [],
    extractedParameters: {},
    speechResponse: '',
    intent: {},
    input: '',
    missingParameters: []
  };

  // Set the input to a clean string of the user's message
  const userInput = msg.cleanContent;
  payload.input = userInput;

  const endpoint = `${apiUrl}/api/v1`;

  try {
    console.log('PAYLOAD: \n', payload);

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    // Check for non-200 responses
    if (!response.ok) {
      throw new Error(`API returned status ${response.status}: ${response.statusText}`);
    }

    const body = await response.json();
    console.log('RESPONSE: \n', body);

    // Send the speech response back to Discord
    if (body.speechResponse) {
      msg.channel.send(body.speechResponse);
    } else {
      msg.channel.send('No response from chatbot API');
    }
  } catch (err) {
    console.error('ERROR: \n', err);
    msg.channel.send('An error occurred while processing your request. Please try again.');
  }
}

module.exports = {
  chatRequest
};