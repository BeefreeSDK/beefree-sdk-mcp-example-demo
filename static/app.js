// Beefree SDK and WebSocket Management
class BeefreeEmailApp {
    constructor() {
        this.ws = null;
        this.beePlugin = null;
        this.currentMessageId = null;
        this.isFirstStreamChunk = false;
        this.previousContentLength = 0;
        this.isGenerating = false;
        this.init();
    }

    async init() {
        // Initialize WebSocket connection first
        this.connectWebSocket();

        // Set up event listeners
        this.setupEventListeners();

        // Initialize Beefree editor
        await this.initializeBeefree();
    }

    async fetchBeefreeToken() {
        try {
            const response = await fetch('/api/auth/token', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`Failed to get token: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Failed to fetch Beefree token:', error);
            this.showError('Failed to authenticate with Beefree. Please check your credentials.');
            throw error;
        }
    }

    async initializeBeefree() {
        if (!window.BeePlugin) {
            console.error('BeePlugin not loaded');
            this.showError('Beefree SDK not loaded. Please refresh the page.');
            return;
        }

        try {
            const token = await this.fetchBeefreeToken();

            const beeConfig = {
                mcpEditorClient: {
                    enabled: true,
                },
                container: "bee-plugin-container",
                language: "en-US",
                specialLinks: [
                    {
                        type: "unsubscribe",
                        label: "SpecialLink.Unsubscribe",
                        link: "http://[unsubscribe]/"
                    }
                ],
                mergeTags: [
                    { name: "tag 1", value: "[tag1]" },
                    { name: "tag 2", value: "[tag2]" }
                ],
                onChange: (jsonFile, response) => {
                    console.log("Template changed:", jsonFile);
                },
                onSave: (jsonFile, htmlFile) => {
                    console.log("Template saved:", jsonFile);
                    this.onSaveDesign(jsonFile, htmlFile);
                },
                onSaveAsTemplate: (jsonFile) => {
                    console.log("Saved as template:", jsonFile);
                    this.onSaveAsTemplate(jsonFile);
                },
                onAutoSave: (jsonFile) => {
                    console.log("Auto-saved:", jsonFile);
                },
                onError: (error) => {
                    console.error("Beefree error:", error);
                    this.showError(`Beefree error: ${error.message || error}`);
                },
                onLoad: () => {
                    console.log("Beefree editor loaded");
                    this.showNotification("Email editor loaded successfully!");
                }
            };

            window.BeePlugin.create(token, beeConfig, (beePluginInstance) => {
                this.beePlugin = beePluginInstance;
                console.log('Beefree plugin initialized');

                beePluginInstance.start({});
            });

        } catch (error) {
            console.error('Failed to initialize Beefree:', error);
            this.showError('Failed to initialize email editor. Please check your configuration.');
        }
    }

    connectWebSocket() {
        const wsUrl = `ws://${window.location.host}/ws`;
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            // Attempt to reconnect after 3 seconds
            setTimeout(() => this.connectWebSocket(), 3000);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'start':
                // Just reset the current message ID, don't create the container yet
                this.currentMessageId = null;
                this.isFirstStreamChunk = true;
                this.previousContentLength = 0; // Reset content tracking for new message
                this.setGeneratingState(true);
                break;

            case 'stream':
                // Create message container on first stream chunk only
                if (this.isFirstStreamChunk) {
                    this.currentMessageId = Date.now();
                    this.addMessage('assistant', '', 'stream', this.currentMessageId);
                    this.isFirstStreamChunk = false;
                }
                // Append only the new content to the existing message
                if (this.currentMessageId) {
                    this.appendToMessage(this.currentMessageId, data.content);
                }
                break;

            case 'progress':
                // Show progress updates from the agent
                this.addMessage('assistant', data.message, 'progress');
                break;

            case 'complete':
                // Mark the streaming message as complete
                if (this.currentMessageId) {
                    this.finalizeMessage(this.currentMessageId);
                }
                this.currentMessageId = null;
                this.isFirstStreamChunk = false;
                this.previousContentLength = 0;
                this.setGeneratingState(false);
                break;

            case 'error':
                this.addMessage('assistant', `❌ ${data.message}`, 'error');
                this.currentMessageId = null;
                this.isFirstStreamChunk = false;
                this.previousContentLength = 0;
                this.setGeneratingState(false);
                break;

            default:
                console.log('Unknown message type:', data.type);
        }
    }

    setupEventListeners() {
        // Send button
        document.getElementById('send-btn').addEventListener('click', () => {
            this.sendMessage();
        });

        // Enter key in textarea
        document.getElementById('chat-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Example prompt cards
        document.addEventListener('click', (e) => {
            if (e.target.closest('.prompt-card')) {
                const promptCard = e.target.closest('.prompt-card');
                const prompt = promptCard.dataset.prompt;
                this.sendPrompt(prompt);
            }
        });
    }

    sendMessage() {
        const input = document.getElementById('chat-input');
        const message = input.value.trim();

        if (!message || this.isGenerating) return;

        // Hide empty state on first message
        this.hideEmptyState();

        // Add user message to chat
        this.addMessage('user', message);

        // Send to WebSocket
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'chat',
                message: message
            }));
        } else {
            this.addMessage('system', 'Connection lost. Reconnecting...', 'error');
        }

        // Clear input
        input.value = '';
    }

    setGeneratingState(generating) {
        this.isGenerating = generating;
        const input = document.getElementById('chat-input');
        const sendBtn = document.getElementById('send-btn');

        if (generating) {
            // Disable input and show loading state
            input.disabled = true;
            input.placeholder = 'Agent is generating response...';
            sendBtn.innerHTML = `
                <svg class="loading-spinner" width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="2" stroke-dasharray="31.416" stroke-dashoffset="31.416">
                        <animate attributeName="stroke-dasharray" dur="2s" values="0 31.416;15.708 15.708;0 31.416" repeatCount="indefinite"/>
                        <animate attributeName="stroke-dashoffset" dur="2s" values="0;-15.708;-31.416" repeatCount="indefinite"/>
                    </circle>
                </svg>
            `;
            sendBtn.disabled = true;
        } else {
            // Re-enable input and restore send button
            input.disabled = false;
            input.placeholder = 'Type your message here...';
            sendBtn.innerHTML = 'Send';
            sendBtn.disabled = false;
        }
    }

    sendPrompt(prompt) {
        if (this.isGenerating) return;

        // Hide empty state
        this.hideEmptyState();

        // Set the prompt in the input field
        document.getElementById('chat-input').value = prompt;

        // Send the message
        this.sendMessage();
    }

    hideEmptyState() {
        const emptyState = document.getElementById('empty-state');
        if (emptyState) {
            emptyState.style.display = 'none';
        }
    }


    addMessage(sender, message, type = '', messageId = null) {
        const messagesDiv = document.getElementById('chat-messages');
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender} ${type}`;
        messageDiv.dataset.messageId = messageId || Date.now();

        const content = `
            <strong>${sender === 'user' ? 'You' : 'Assistant'}:</strong>
            <div class="message-content">${this.formatMessage(message)}</div>
        `;

        messageDiv.innerHTML = content;
        messagesDiv.appendChild(messageDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    appendToMessage(messageId, fullContent) {
        const messageDiv = document.querySelector(`[data-message-id="${messageId}"]`);
        if (messageDiv) {
            const contentDiv = messageDiv.querySelector('.message-content');
            if (contentDiv) {
                // Extract only the new portion of content that we haven't displayed yet
                const newContent = fullContent.substring(this.previousContentLength);

                // Only append if there's actually new content
                if (newContent) {
                    contentDiv.innerHTML += this.formatMessage(newContent);
                    this.previousContentLength = fullContent.length;
                }

                // Scroll to bottom
                const messagesDiv = document.getElementById('chat-messages');
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }
        }
    }

    finalizeMessage(messageId) {
        const messageDiv = document.querySelector(`[data-message-id="${messageId}"]`);
        if (messageDiv) {
            // Remove the stream class to stop the pulsing animation
            messageDiv.classList.remove('stream');
            messageDiv.classList.add('complete');
        }
    }


    formatMessage(message) {
        // Convert line breaks and escape HTML
        return this.escapeHtml(message).replace(/\n/g, '<br>');
    }

    downloadFile(content, filename, mimeType) {
        // Create a blob with the file content
        const blob = new Blob([content], { type: mimeType });

        // Create a temporary download link
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;

        // Append to body, click, and remove
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        // Clean up the blob URL
        URL.revokeObjectURL(link.href);
    }

    onSaveDesign(json, html) {
        console.log('Design saved:', json);

        // Generate timestamp for consistent file naming
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);

        // Download both JSON and HTML files
        this.downloadFile(JSON.stringify(json, null, 2), `email-template-${timestamp}.json`, 'application/json');
        this.downloadFile(html, `email-template-${timestamp}.html`, 'text/html');

        this.showNotification('Email design saved and downloaded successfully!');
    }

    onSaveAsTemplate(json) {
        console.log('Saved as template:', json);
        this.showNotification('Template saved successfully!');
    }

    showNotification(message, type = 'success') {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${type === 'error' ? '#ef4444' : '#10b981'};
            color: white;
            padding: 12px 20px;
            border-radius: 4px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            z-index: 10000;
            animation: slideIn 0.3s ease;
            max-width: 300px;
            word-wrap: break-word;
        `;

        document.body.appendChild(notification);
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, type === 'error' ? 5000 : 3000);
    }

    showError(message) {
        this.showNotification(message, 'error');
    }

    escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }
}

// Add CSS animation for notifications
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }

    .message.stream .message-content {
        opacity: 0.8;
        animation: pulse 1s infinite;
    }

    @keyframes pulse {
        0%, 100% { opacity: 0.8; }
        50% { opacity: 1; }
    }

    /* Ensure the Beefree container takes full space */
    #bee-plugin-container {
        width: 100%;
        height: 100%;
        min-height: 600px;
        background: #f5f5f5;
        border: 1px solid #ddd;
        border-radius: 4px;
    }
`;
document.head.appendChild(style);

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new BeefreeEmailApp();
});