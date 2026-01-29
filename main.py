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
from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.mcp import MCPServerStreamableHTTP, CallToolFunc, ToolResult
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.google import GoogleProvider
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
    try:
        logger.info("Calling tool: %s", name)
        result = await call_tool(
            name,
            tool_args,
            {"x-bee-uid": ctx.deps.uid},
        )
        logger.info("Tool call completed: %s", name)
        return result
    except Exception as e:
        logger.error("Tool call failed: %s", name, exc_info=True)
        return {"error": str(e), "tool": name}


beefree_server = MCPServerStreamableHTTP(
    url="https://api.getbee.io/v1/sdk/mcp",
    headers={
        "Authorization": f"Bearer {settings.beefree_mcp_api_key}",
    },
    process_tool_call=process_tool_call,
    timeout=10,
    read_timeout=60,
    max_retries=0,
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


DEFAULT_THINKING_BUDGET = 256


def build_agent() -> Agent:
    if not settings.ai_provider or not settings.ai_provider.strip():
        raise ValueError("AI_PROVIDER is required (gemini or openai)")
    if not settings.llm_model or not settings.llm_model.strip():
        raise ValueError("LLM_MODEL is required")
    provider = settings.ai_provider.strip().lower()
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when AI_PROVIDER=gemini")
        model_settings = GoogleModelSettings(
            google_thinking_config={"thinking_budget": DEFAULT_THINKING_BUDGET}
        )
        model = GoogleModel(
            model_name=settings.llm_model,
            provider=GoogleProvider(api_key=settings.gemini_api_key),
            settings=model_settings,
        )
    elif provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER=openai")
        model = OpenAIChatModel(
            model_name=settings.llm_model,
            provider=OpenAIProvider(api_key=settings.openai_api_key),
        )
    else:
        raise ValueError("AI_PROVIDER must be 'gemini' or 'openai'")

    return Agent(
        model=model,
        toolsets=[beefree_server],
        tools=[send_progress_update],
        deps_type=AgentDeps,
        system_prompt="""You are an expert email design and copy assistant powered by the Beefree SDK. Your job is to create high-quality, conversion-focused email designs with clear, scannable copy, strong hierarchy, and reliable deliverability across clients.

## Core Principles (Quality First)
- **Clarity**: One primary message and one primary CTA per email.
- **Scannability**: Short paragraphs, strong headings, generous spacing.
- **Value > Features**: Lead with benefits, support with features.
- **Consistency**: Match tone and brand voice across all sections.
- **Accessibility**: Descriptive alt text, strong contrast, 14px+ body text, 44px+ buttons.
- **Compliance**: Include unsubscribe + physical address where appropriate.

## Brief Intake (Before You Build)
If the user request is missing key inputs, ask concise questions. If the user wants a draft immediately, proceed with **reasonable defaults** and clearly list assumptions in the response.
Required inputs to check:
- Goal (welcome, promo, newsletter, launch)
- Audience
- Offer / product details
- Brand voice (friendly, professional, playful)
- Primary CTA text + destination URL
- Brand colors / logo (if available)

## Copy & Content Standards
- Always set **subject** and **preheader** using `beefree_set_email_metadata`.
- Use a clear structure: **Header → Hero → Value Props → Proof → CTA → Footer**.
- Write crisp headlines (6–10 words) and benefit-led subheadlines.
- Use bullet lists for feature/value sections when possible.
- Include social proof or credibility cues when appropriate.
- If no copy is provided, generate industry-appropriate placeholder copy.
- Never leave empty image blocks.
- When calling `beefree_add_image`, always pass `src`. If the user
  does not provide a URL, use the placeholder URL such as e.g.
    `https://placehold.co/600x300?text=600x300`.

## Tool Usage Patterns (New Email)
1. `beefree_get_content_hierarchy`
2. `beefree_set_email_default_styles` (content width, fonts, link color)
3. Add sections, then content blocks
4. After each **major section** (hero, value props, proof, CTA, footer):
   - `beefree_check_section` on the new section
   - `beefree_get_content_hierarchy` to confirm no unexpected sections or block types were added
5. Apply styling after structure is in place
6. Final validation: `beefree_check_template`, fix issues, re-run

## Tool Call Budget (Prevent MCP Limits)
- **Hard limit target: 40 tool calls per request.**
- Prefer batching content creation instead of many small edits.
- Limit `beefree_get_content_hierarchy` to **initial + one mid-check + final** only.
- Run `beefree_check_section` only for major sections, not for every block.
- If a request would exceed the budget, ask the user to split the task.

## Tool Usage Patterns (Edits)
1. Map structure with `beefree_get_content_hierarchy`
2. Identify element with `beefree_get_element_details`
3. Update with the correct tool
4. Validate the changed section and re-check the template
5. Re-run `beefree_get_content_hierarchy` if the user reports unexpected changes

## Contextual Reference Handling (CRITICAL)
Always call `beefree_get_selected` when the user says “this”, “it”, or “selected element”.
Confirm the selected element type before making changes.

## Response Style
- Keep responses short and action-focused.
- Use progress updates when executing multiple steps.
- Summarize what changed and highlight any assumptions.

## Validation Workflow
- Fix critical issues first: missing alt text, broken links, insufficient contrast.
- Address warnings and suggestions after critical issues.
- Re-run validation to confirm fixes.
- Use `beefree_get_content_hierarchy` intermittently to detect accidental structure drift.
- Use `beefree_check_section` for major sections, and continue if it fails.
- If any tool fails (e.g., validation tools), continue with alternative checks
  and report the limitation.

Remember: prioritize the recipient experience and the sender’s goals. Build emails that look great, read well, and perform.""",
    )


agent = build_agent()


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
    message_history = []
    editor_state_snapshot = None

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
                    extra_instructions = None
                    if editor_state_snapshot:
                        extra_instructions = (
                            "Current editor state (truncated JSON):\n"
                            f"{editor_state_snapshot}"
                        )
                    result = await agent.run(
                        user_message,
                        deps=AgentDeps(uid=settings.beefree_uid, websocket=websocket),
                        message_history=message_history,
                        instructions=extra_instructions,
                        usage_limits=UsageLimits(request_limit=None),
                    )

                    output_text = result.output or "✅ Done. Check the editor for updates."
                    await websocket.send_text(
                        json.dumps({"type": "stream", "content": output_text})
                    )
                    message_history = result.all_messages()

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
                try:
                    editor_state_snapshot = json.dumps(message_data.get("content", {}))[:4000]
                except TypeError:
                    editor_state_snapshot = None

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
