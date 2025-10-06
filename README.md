# Beefree SDK + PydanticAI MCP Showcase

A demonstration application showcasing the integration of Beefree SDK's drag-and-drop email editor with PydanticAI agents using the Model Context Protocol (MCP).

## Features

- **AI-Powered Email Design**: Use natural language to create and modify email templates
- **Drag-and-Drop Editor**: Full Beefree SDK email editor integration
- **Real-time Streaming**: WebSocket-based streaming chat interface
- **MCP Integration**: Direct connection to Beefree's Streamble HTTP MCP server
- **Modern Tooling**: Built with uv for fast dependency management

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for package management (recommended)
- Beefree SDK account ([Get credentials here](https://developers.beefree.io/))
- OpenAI API key

## Quick Start

### 1. Clone and Install

```bash
# Clone the repository
git clone <repository-url>
cd beefree_mcp_example

# Install with uv
uv sync
```

### 2. Configure Environment

Copy the example environment file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
BEEFREE_CLIENT_ID=your_beefree_client_id
BEEFREE_CLIENT_SECRET=your_beefree_client_secret
BEEFREE_MCP_API_KEY=your_beefree_mcp_api_key
OPENAI_API_KEY=your_llm_api_key
```

### 3. Run the Application

```bash
# With uv
uv run python main.py
```

The application will be available at `http://localhost:8000`

## How It Works

1. **User Input**: User types a natural language request in the chat interface
2. **Streaming Processing**: PydanticAI agent processes using `agent.run_stream()`
3. **MCP Execution**: Direct HTTP calls to Beefree's MCP server modify the email template
4. **Real-time Updates**: Streaming responses show the AI's thought process
5. **Editor Integration**: Changes are reflected in the Beefree editor

## Resources

- [Beefree SDK Documentation](https://docs.beefree.io/)
- [PydanticAI Documentation](https://ai.pydantic.dev/)
- [PydanticAI MCP Integration](https://ai.pydantic.dev/mcp/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [uv Documentation](https://docs.astral.sh/uv/)
