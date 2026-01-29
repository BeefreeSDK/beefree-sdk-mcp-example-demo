# Email Creation with AI Agents | Beefree SDK + PydanticAI MCP Showcase

Are you exploring agentic email design? We believe the future of content design means having AI agents and humans work seamlessly together to create content — and this simple demo app shows you how to create a design experience that does just that. 

It connects the [Beefree SDK](https://developers.beefree.io/) (the most intuitive drag-and-drop email editor in the market) with a [PydanticAI agent](https://ai.pydantic.dev/) using the Model Context Protocol (MCP), and supports Anthropic, OpenAI, and Gemini as the LLM provider.

**Here's what you can achieve:** 

- **AI-Powered Email Design**: Use natural language to create and modify email templates  
- **WYSIWYG Editor**: Allow humans to easily edit drafts created by AI in the intuitive, drag-and-drop editor provided by the Beefree SDK

**What powers this experience:** 

* **Real-time Streaming:** WebSocket-based streaming chat interface  
* **MCP Integration:** Direct connection to Beefree's Streamble HTTP MCP Server.  
* **Modern Tooling**: Built with uv for fast dependency management

## Prerequisites

- Python 3.13+  
- [uv](https://docs.astral.sh/uv/) for package management (recommended)  
- Beefree SDK account (If you already have an account, you can [get your credentials here](https://developers.beefree.io/). If you're new to Beefree SDK, you can [sign up for a free account](https://developers.beefree.io/signup).)  
- Anthropic, OpenAI, or Gemini API key
- Beta access. Learn how to request access to the beta in our [Beefree SDK MCP Server (Beta) documentation](https://docs.beefree.io/beefree-sdk/early-access/beefree-sdk-mcp-server-beta).

## Quick start

### 1. Clone and install

```shell
# Clone the repository
git clone <repository-url>
cd beefree_mcp_example

# Install with uv
uv sync
```

### 2. Configure environment

Create a `.env` file and add your credentials. Pick the example that matches your provider.
Anthropic:
```
AI_PROVIDER=anthropic
BEEFREE_CLIENT_ID=your_beefree_client_id
BEEFREE_CLIENT_SECRET=your_beefree_client_secret
BEEFREE_MCP_API_KEY=your_beefree_mcp_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
LLM_MODEL=claude-opus-4.5
```

OpenAI:
```
AI_PROVIDER=openai
BEEFREE_CLIENT_ID=your_beefree_client_id
BEEFREE_CLIENT_SECRET=your_beefree_client_secret
BEEFREE_MCP_API_KEY=your_beefree_mcp_api_key
OPENAI_API_KEY=your_openai_api_key
LLM_MODEL=gpt-5.2
```

Gemini:
```
AI_PROVIDER=gemini
BEEFREE_CLIENT_ID=your_beefree_client_id
BEEFREE_CLIENT_SECRET=your_beefree_client_secret
BEEFREE_MCP_API_KEY=your_beefree_mcp_api_key
GEMINI_API_KEY=your_gemini_api_key
LLM_MODEL=gemini-2.5-pro
```

### 3. Run the application

```shell
# With uv
uv run python main.py
```

The application will be available at `http://localhost:8000`

## How it works

1. **User Input**: The user types a natural language request in the chat interface.  
2. **Agent Run**: The PydanticAI agent runs with conversation history and editor context.  
3. **MCP Execution**: Direct HTTP calls to Beefree's MCP server modify the email template.  
4. **Progress Updates**: The UI shows step-by-step progress messages.  
5. **Editor Integration**: Changes are reflected in the Beefree editor.

## Resources

**About the Beefree SDK**

- [Beefree SDK Documentation](https://docs.beefree.io/)  
- [Beefree SDK MCP Server Documentation](https://docs.beefree.io/beefree-sdk/early-access/beefree-sdk-mcp-server-beta)

**About PydanticAI:**

- [PydanticAI Documentation](https://ai.pydantic.dev/)  
- [PydanticAI MCP Integration](https://ai.pydantic.dev/mcp/)

**More resources:**

- MCP tool list for this demo: `mcp-tool-list.md`
- What's a [Model Context Protocol](https://modelcontextprotocol.io/)?  
- [uv Documentation](https://docs.astral.sh/uv/)
