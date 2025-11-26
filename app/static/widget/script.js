(() => {
  const styles = `
    .iky-chat-widget {
      position: fixed;
      bottom: 20px;
      right: 20px;
      z-index: 1000;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    }

    .iky-chat-button {
      width: 60px;
      height: 60px;
      border-radius: 30px;
      background-color: #22c55e;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 0.2s;
    }

    .iky-chat-button:hover {
      transform: scale(1.05);
    }

    .iky-chat-button svg {
      width: 28px;
      height: 28px;
      fill: white;
    }

    .iky-chat-window {
      position: fixed;
      bottom: 90px;
      right: 20px;
      width: 380px;
      height: 600px;
      background: white;
      border-radius: 16px;
      box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: all 0.3s;
      opacity: 0;
      transform: translateY(20px);
      pointer-events: none;
    }

    .iky-chat-window.open {
      opacity: 1;
      transform: translateY(0);
      pointer-events: all;
    }

    .iky-chat-header {
      padding: 20px;
      background: #22c55e;
      color: white;
    }

    .iky-chat-title {
      font-size: 18px;
      font-weight: 600;
      margin: 0;
    }

    .iky-chat-subtitle {
      font-size: 14px;
      opacity: 0.8;
      margin: 4px 0 0;
    }

    .iky-chat-messages {
      flex: 1;
      padding: 20px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .iky-message {
      max-width: 80%;
      padding: 12px 16px;
      border-radius: 16px;
      font-size: 14px;
      line-height: 1.4;
      animation: messageSlideIn 0.3s ease;
      word-wrap: break-word;
      overflow-wrap: break-word;
    }

    .iky-message.bot {
      background: #f3f4f6;
      border-bottom-left-radius: 4px;
      align-self: flex-start;
    }

    .iky-message.user {
      background: #22c55e;
      color: white;
      border-bottom-right-radius: 4px;
      align-self: flex-end;
    }

    .iky-chat-input {
      padding: 20px;
      border-top: 1px solid #e5e7eb;
      background: white;
    }

    .iky-input-form {
      display: flex;
      gap: 8px;
    }

    .iky-input-field {
      flex: 1;
      padding: 12px 16px;
      border: 1px solid #e5e7eb;
      border-radius: 24px;
      font-size: 14px;
      outline: none;
      transition: border-color 0.2s;
    }

    .iky-input-field:focus {
      border-color: #22c55e;
    }

    .iky-send-button {
      width: 40px;
      height: 40px;
      border-radius: 20px;
      background: #22c55e;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background-color 0.2s;
    }

    .iky-send-button:hover {
      background: #16a34a;
    }

    .iky-send-button svg {
      width: 20px;
      height: 20px;
      fill: white;
    }

    .iky-typing {
      display: flex;
      gap: 4px;
      padding: 12px 16px;
      background: #f3f4f6;
      border-radius: 16px;
      border-bottom-left-radius: 4px;
      align-self: flex-start;
      max-width: 80%;
    }

    .iky-typing-dot {
      width: 8px;
      height: 8px;
      background: #9ca3af;
      border-radius: 4px;
      animation: typingBounce 0.5s infinite;
    }

    .iky-typing-dot:nth-child(2) { animation-delay: 0.1s; }
    .iky-typing-dot:nth-child(3) { animation-delay: 0.2s; }

    @keyframes messageSlideIn {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    @keyframes typingBounce {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-4px); }
    }

    @media (max-width: 480px) {
      .iky-chat-window {
        width: calc(100vw - 40px);
        height: calc(100vh - 120px);
      }
    }
  `;

  /**
   * Escapes HTML special characters to prevent XSS attacks.
   * @param {string} text - The text to escape
   * @returns {string} Escaped text safe for DOM insertion
   */
  function escapeHtml(text) {
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, (char) => map[char]);
  }

  /**
   * Gets the base URL for API calls from data-attribute or window config.
   * @returns {string} The base URL for the API endpoint
   */
  function getBaseUrl() {
    // Check for data-attribute on script tag
    const scriptTag = document.currentScript || document.querySelector('script[data-iky-base-url]');
    if (scriptTag && scriptTag.dataset.ikyBaseUrl) {
      return scriptTag.dataset.ikyBaseUrl;
    }
    // Check for window config
    if (window.iky_base_url) {
      return window.iky_base_url;
    }
    // Default fallback
    return window.location.origin;
  }

  class ChatWidget {
    constructor() {
      this.isOpen = false;
      this.isTyping = false;
      this.baseUrl = getBaseUrl();
      this.currentState = {
        thread_id: this.uuid(),
        text: "/init_conversation",
        context: {},
      };
      this.response = [];
      this.createElements();
      this.attachEventListeners();
      this.initChat();
    }

    createElements() {
      // Add styles
      const styleSheet = document.createElement('style');
      styleSheet.textContent = styles;
      document.head.appendChild(styleSheet);

      // Create widget container
      this.container = document.createElement('div');
      this.container.className = 'iky-chat-widget';

      // Create chat button with SVG icon
      this.button = document.createElement('div');
      this.button.className = 'iky-chat-button';
      const buttonSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      buttonSvg.setAttribute('viewBox', '0 0 24 24');
      const buttonPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      buttonPath.setAttribute('d', 'M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z');
      buttonSvg.appendChild(buttonPath);
      this.button.appendChild(buttonSvg);

      // Create chat window
      this.window = document.createElement('div');
      this.window.className = 'iky-chat-window';

      // Header
      const header = document.createElement('div');
      header.className = 'iky-chat-header';
      const title = document.createElement('h2');
      title.className = 'iky-chat-title';
      title.textContent = 'Chat with us';
      const subtitle = document.createElement('p');
      subtitle.className = 'iky-chat-subtitle';
      subtitle.textContent = 'You are talking to an AI chatbot';
      header.appendChild(title);
      header.appendChild(subtitle);

      // Messages container
      this.messages = document.createElement('div');
      this.messages.className = 'iky-chat-messages';

      // Input section
      const inputSection = document.createElement('div');
      inputSection.className = 'iky-chat-input';
      this.form = document.createElement('form');
      this.form.className = 'iky-input-form';
      this.input = document.createElement('input');
      this.input.type = 'text';
      this.input.className = 'iky-input-field';
      this.input.placeholder = 'Type your message...';
      const sendButton = document.createElement('button');
      sendButton.type = 'submit';
      sendButton.className = 'iky-send-button';
      const sendSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      sendSvg.setAttribute('viewBox', '0 0 24 24');
      const sendPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      sendPath.setAttribute('d', 'M2.01 21L23 12 2.01 3 2 10l15 2-15 2z');
      sendSvg.appendChild(sendPath);
      sendButton.appendChild(sendSvg);
      this.form.appendChild(this.input);
      this.form.appendChild(sendButton);
      inputSection.appendChild(this.form);

      // Assemble window
      this.window.appendChild(header);
      this.window.appendChild(this.messages);
      this.window.appendChild(inputSection);

      // Append elements to DOM
      this.container.appendChild(this.window);
      this.container.appendChild(this.button);
      document.body.appendChild(this.container);
    }

    attachEventListeners() {
      // Toggle chat window
      this.button.addEventListener('click', () => this.toggleChat());

      // Handle form submission
      this.form.addEventListener('submit', (e) => {
        e.preventDefault();
        const message = this.input.value.trim();
        if (message) {
          this.sendMessage(message);
          this.input.value = '';
        }
      });
    }

    toggleChat() {
      this.isOpen = !this.isOpen;
      this.window.classList.toggle('open', this.isOpen);
      if (this.isOpen) {
        this.input.focus();
      }
    }

    /**
     * Adds a message to the chat window with sanitized content.
     * @param {string} content - The message text to display
     * @param {boolean} isUser - Whether the message is from the user
     */
    addMessage(content, isUser = false) {
      const message = document.createElement('div');
      message.className = `iky-message ${isUser ? 'user' : 'bot'}`;
      message.textContent = content;
      this.messages.appendChild(message);
      this.scrollToBottom();
    }

    showTyping() {
      if (this.isTyping) return;
      this.isTyping = true;

      const typing = document.createElement('div');
      typing.className = 'iky-typing';
      for (let i = 0; i < 3; i++) {
        const dot = document.createElement('div');
        dot.className = 'iky-typing-dot';
        typing.appendChild(dot);
      }
      this.messages.appendChild(typing);
      this.scrollToBottom();
    }

    hideTyping() {
      this.isTyping = false;
      const typing = this.messages.querySelector('.iky-typing');
      if (typing) {
        typing.remove();
      }
    }

    scrollToBottom() {
      this.messages.scrollTop = this.messages.scrollHeight;
    }

    /**
     * Generates a UUID v4 string.
     * @returns {string} A UUID v4 string
     */
    uuid() {
      return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
          const r = Math.random() * 16 | 0;
          const v = c === 'x' ? r : (r & 0x3 | 0x8);
          return v.toString(16);
      });
    }

    /**
     * Initializes the chat by sending the initial conversation message.
     */
    async initChat() {
      try {
        const response = await fetch(`${this.baseUrl}/bots/channels/rest/webbook`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(this.currentState),
        });

        const data = await response.json();
        this.response = { ...data };

        // Add bot response(s)
        if (Array.isArray(data)) {
          data.forEach((response, index) => {
            setTimeout(() => {
              this.addMessage(response.text || '');
            }, index * 500);
          });
        } else if (data && data.text) {
          this.addMessage(data.text);
        }
      } catch (error) {
        console.error('Error initializing chat:', error);
        this.addMessage('Sorry, I had trouble starting up. Please try refreshing the page.');
      }
    }

    /**
     * Sends a user message and retrieves bot response.
     * @param {string} message - The user message to send
     */
    async sendMessage(message) {
      // Add user message (sanitized via textContent)
      this.addMessage(message, true);

      // Show typing indicator
      this.showTyping();

      try {
        const response = await fetch(`${this.baseUrl}/bots/channels/rest/webbook`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            ...this.currentState,
            text: message
          }),
        });

        const data = await response.json();
        this.response = { ...data };

        // Hide typing indicator
        this.hideTyping();

        // Add bot response(s)
        if (Array.isArray(data)) {
          data.forEach((response, index) => {
            setTimeout(() => {
              this.addMessage(response.text || '');
            }, index * 500);
          });
        } else if (data && data.text) {
          this.addMessage(data.text);
        }
      } catch (error) {
        console.error('Error sending message:', error);
        this.hideTyping();
        this.addMessage('Sorry, something went wrong. Please try again later.');
      }
    }
  }

  // Initialize widget when DOM is ready
  window.addEventListener('load', () => {
    new ChatWidget();
  });
})();