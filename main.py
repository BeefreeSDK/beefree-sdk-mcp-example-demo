from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPServerStreamableHTTP, CallToolFunc, ToolResult
from pydantic_ai.models.openai import (\
    OpenAIChatModel,
    OpenAIModelSettings,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.providers.openai import OpenAIProvider

from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    uid: str
    websocket: Optional[WebSocket] = None


async def process_tool_call(
    ctx: RunContext[AgentDeps],
    call_tool: CallToolFunc,
    name: str,
    tool_args: dict[str, Any],
) -> ToolResult:
    return await call_tool(
        name,
        tool_args,
        {"x-bee-uid": ctx.deps.uid},
    )


beefree_server = MCPServerStreamableHTTP(
    url="https://api.getbee.io/v1/sdk/mcp",
    headers={
        "Authorization": f"Bearer {settings.beefree_mcp_api_key}",
    },
    process_tool_call=process_tool_call,
)


async def send_progress_update(ctx: RunContext[AgentDeps], message: str) -> str:
    """Send a progress update to the user through WebSocket.

    Args:
        ctx: The run context containing dependencies
        message: The progress message to send to the user

    Returns:
        A confirmation message
    """
    if ctx.deps.websocket:
        try:
            await ctx.deps.websocket.send_text(
                json.dumps({"type": "progress", "message": message})
            )
            logger.info(f"Sent progress update: {message}")
            return f"Progress update sent: {message}"
        except Exception as e:
            logger.error(f"Failed to send progress update: {e}")
            return f"Failed to send progress update: {str(e)}"
    else:
        logger.warning("No WebSocket connection available for progress update")
        return "No WebSocket connection available"


agent = Agent(
    model=OpenAIChatModel(
        model_name=settings.llm_model,
        provider=OpenAIProvider(api_key=settings.openai_api_key),
    ),
    model_settings=OpenAIModelSettings(
        openai_reasoning_effort="minimal",
        responses_settings=OpenAIResponsesModelSettings(openai_text_verbosity="low"),
    ),
    toolsets=[beefree_server],
    tools=[send_progress_update],
    deps_type=AgentDeps,
    system_prompt="""You are an AI assistant that helps users create and edit email templates using the Beefree SDK.

You have access to powerful tools through the Beefree MCP server that allow you to:
- Add and modify sections (rows) with columns
- Add content blocks like titles, paragraphs, images, buttons, social icons, etc.
- Manage templates and validate designs
- Set email metadata and styles
- Send progress updates to keep the user informed

IMPORTANT: Use the send_progress_update tool to inform the user about what you're doing as you work. Send brief, clear updates like:
- "Setting up email defaults and styles"
- "Creating header section"
- "Adding hero section with image"
- "Inserting content blocks"
- "Adding call-to-action buttons"
- "Creating footer with social links"
- "Validating email template"

Send these updates BEFORE performing major actions, not after. This helps users understand what's happening in real-time.

Examples of what you can help with:
- "Add a header" -> First send progress update, then use section and title tools
- "Create a two-column layout" -> Send progress update, then add a section with 2 columns
- "Add a call to action" -> Send progress update, then add a button with appropriate styling
- "Add footer with social links" -> Send progress update, then add section with social media icons
- "Make it look professional" -> Send progress updates as you apply styling and layout

Be creative and helpful in designing attractive email templates. Always keep the user informed of your progress.""",
)


app = FastAPI(
    title="Beefree MCP enabled agent example",
)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse(static_dir / "index.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection established")

    if not agent:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "message": "Agent not initialized. Please check your configuration.",
                }
            )
        )
        await websocket.close()
        return

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            if message_data["type"] == "chat":
                user_message = message_data["message"]
                logger.info(f"Received message: {user_message}")

                # Send start of processing
                await websocket.send_text(
                    json.dumps(
                        {"type": "start", "message": "Processing your request..."}
                    )
                )

                try:
                    async with agent.run_stream(
                        user_message,
                        deps=AgentDeps(uid=settings.beefree_uid, websocket=websocket),
                    ) as result:
                        async for text in result.stream_text(debounce_by=0.01):
                            await websocket.send_text(
                                json.dumps({"type": "stream", "content": text})
                            )

                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "complete",
                                "message": "Request completed successfully",
                            }
                        )
                    )

                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": f"Error: {str(e)}"})
                    )

            elif message_data["type"] == "editor_state":
                logger.info("Received editor state update")

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


@app.post("/api/auth/token")
async def get_beefree_token():
    """Get Beefree authentication token"""
    if not settings.beefree_client_id or not settings.beefree_client_secret:
        raise HTTPException(
            status_code=500,
            detail="Beefree SDK credentials not configured. Please check your .env file",
        )

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "client_id": settings.beefree_client_id,
                "client_secret": settings.beefree_client_secret,
                "uid": settings.beefree_uid,
            }
            response = await client.post(
                "https://bee-auth.getbee.io/loginV2",
                headers={"Content-Type": "application/json"},
                json=payload,
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to authenticate with Beefree: {response.text}",
                )

            return response.json()

    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to connect to Beefree auth service: {str(e)}",
        )


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "beefree-mcp-example",
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app", host=settings.app_host, port=settings.app_port, log_level="info"
    )
