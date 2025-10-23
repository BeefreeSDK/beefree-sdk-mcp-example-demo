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


async def fetch_figma_design(
    ctx: RunContext[AgentDeps], figma_url: str
) -> str:
    """Fetch design data from Figma API.

    Args:
        ctx: The run context containing dependencies
        figma_url: The Figma file URL (e.g., https://www.figma.com/file/FILE_KEY/...)

    Returns:
        A JSON string containing the Figma design data including:
        - document structure
        - components and their properties
        - styles (colors, typography)
        - layout information
        - text content
    """
    await send_progress_update(ctx, "Fetching design from Figma...")
    
    try:
        # Validate Figma token exists
        if not settings.figma_token or settings.figma_token == "your_figma_access_token":
            error_msg = "Figma token not configured. Please add FIGMA_TOKEN to your .env file."
            logger.error(error_msg)
            await send_progress_update(ctx, f"❌ {error_msg}")
            return json.dumps({"error": error_msg})
        
        # Extract file key from Figma URL
        # URL format: https://www.figma.com/file/{file_key}/{title} or https://www.figma.com/design/{file_key}/{title}
        import re
        match = re.search(r'/(file|design)/([a-zA-Z0-9]+)', figma_url)
        if not match:
            error_msg = "Invalid Figma URL. Expected format: https://www.figma.com/file/FILE_KEY/... or https://www.figma.com/design/FILE_KEY/..."
            logger.error(error_msg)
            await send_progress_update(ctx, f"❌ {error_msg}")
            return json.dumps({"error": error_msg})
        
        file_key = match.group(2)
        logger.info(f"Extracted Figma file key: {file_key}")
        
        async with httpx.AsyncClient() as client:
            # Fetch file data from Figma API using token from config
            headers = {
                "X-Figma-Token": settings.figma_token,
            }
            
            await send_progress_update(ctx, f"Connecting to Figma API for file: {file_key}...")
            
            response = await client.get(
                f"https://api.figma.com/v1/files/{file_key}",
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code == 403:
                error_msg = "Figma API authentication failed. Please check your FIGMA_TOKEN in .env file."
                logger.error(error_msg)
                await send_progress_update(ctx, f"❌ {error_msg}")
                return json.dumps({
                    "error": error_msg,
                    "status_code": 403,
                    "suggestion": "Get a valid token from https://www.figma.com/developers/api#access-tokens"
                })
            elif response.status_code == 404:
                error_msg = "Figma file not found. Please check the URL or file permissions."
                logger.error(error_msg)
                await send_progress_update(ctx, f"❌ {error_msg}")
                return json.dumps({
                    "error": error_msg,
                    "status_code": 404
                })
            elif response.status_code != 200:
                error_msg = f"Figma API error ({response.status_code}): {response.text}"
                logger.error(error_msg)
                await send_progress_update(ctx, f"❌ {error_msg}")
                return json.dumps({
                    "error": error_msg,
                    "status_code": response.status_code
                })
            
            figma_data = response.json()
            
            await send_progress_update(ctx, "Successfully retrieved Figma design. Analyzing structure...")
            
            # Validate response structure
            if not isinstance(figma_data, dict):
                error_msg = "Invalid response from Figma API"
                logger.error(error_msg)
                await send_progress_update(ctx, f"❌ {error_msg}")
                return json.dumps({"error": error_msg})
            
            # Extract relevant design information
            design_info = {
                "name": figma_data.get("name", "Untitled"),
                "document": figma_data.get("document", {}),
                "components": figma_data.get("components", {}),
                "styles": figma_data.get("styles", {}),
                "schemaVersion": figma_data.get("schemaVersion"),
            }
            
            # Simplify the structure for better AI comprehension
            simplified = {
                "file_name": design_info["name"],
                "pages": [],
                "color_styles": {},
                "text_styles": {},
            }
            
            # Extract pages and their content
            if "children" in design_info["document"]:
                for page in design_info["document"]["children"]:
                    try:
                        page_info = {
                            "name": page.get("name", "Untitled Page"),
                            "frames": []
                        }
                        
                        if "children" in page:
                            for child in page["children"]:
                                try:
                                    frame_info = extract_frame_info(child)
                                    if frame_info:
                                        page_info["frames"].append(frame_info)
                                except Exception as e:
                                    logger.warning(f"Error extracting frame info: {str(e)}")
                                    continue
                        
                        simplified["pages"].append(page_info)
                    except Exception as e:
                        logger.warning(f"Error processing page: {str(e)}")
                        continue
            
            await send_progress_update(ctx, "✅ Figma design analysis complete. Ready to recreate in email template.")
            
            return json.dumps(simplified, indent=2)
            
    except httpx.TimeoutException:
        error_msg = "Request to Figma API timed out. Please try again."
        logger.error(error_msg)
        await send_progress_update(ctx, f"❌ {error_msg}")
        return json.dumps({"error": error_msg})
    except httpx.HTTPError as e:
        error_msg = f"HTTP error while connecting to Figma API: {str(e)}"
        logger.error(error_msg, exc_info=True)
        await send_progress_update(ctx, f"❌ {error_msg}")
        return json.dumps({"error": error_msg})
    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse Figma API response: {str(e)}"
        logger.error(error_msg, exc_info=True)
        await send_progress_update(ctx, f"❌ {error_msg}")
        return json.dumps({"error": error_msg})
    except KeyError as e:
        error_msg = f"Unexpected Figma data structure. Missing key: {str(e)}"
        logger.error(error_msg, exc_info=True)
        await send_progress_update(ctx, f"❌ {error_msg}")
        return json.dumps({"error": error_msg})
    except Exception as e:
        error_msg = f"Failed to fetch Figma design: {str(e)}"
        logger.error(error_msg, exc_info=True)
        await send_progress_update(ctx, f"❌ {error_msg}")
        return json.dumps({
            "error": error_msg,
            "type": type(e).__name__
        })


def extract_frame_info(node: dict) -> Optional[dict]:
    """Extract relevant information from a Figma frame/node.
    
    Args:
        node: A Figma node dictionary
        
    Returns:
        Simplified frame information with layout, colors, text, and children
    """
    try:
        if not isinstance(node, dict):
            return None
        
        frame_info = {
            "name": node.get("name", "Unnamed"),
            "type": node.get("type", "UNKNOWN"),
        }
        
        # Safely extract dimensions
        bounding_box = node.get("absoluteBoundingBox", {})
        if isinstance(bounding_box, dict):
            frame_info["width"] = bounding_box.get("width")
            frame_info["height"] = bounding_box.get("height")
        
        # Extract background color
        if "backgroundColor" in node:
            try:
                bg = node["backgroundColor"]
                if isinstance(bg, dict):
                    r = int(bg.get('r', 0) * 255)
                    g = int(bg.get('g', 0) * 255)
                    b = int(bg.get('b', 0) * 255)
                    a = bg.get('a', 1)
                    frame_info["backgroundColor"] = f"rgba({r}, {g}, {b}, {a})"
            except (TypeError, ValueError) as e:
                logger.warning(f"Error parsing backgroundColor: {e}")
        
        # Extract text content
        if node.get("type") == "TEXT" and "characters" in node:
            frame_info["text"] = node["characters"]
            
            # Extract text style
            if "style" in node and isinstance(node["style"], dict):
                try:
                    style = node["style"]
                    frame_info["textStyle"] = {
                        "fontSize": style.get("fontSize"),
                        "fontFamily": style.get("fontFamily"),
                        "fontWeight": style.get("fontWeight"),
                        "textAlign": style.get("textAlignHorizontal", "LEFT").lower(),
                    }
                    
                    # Extract text color
                    if "fills" in node and isinstance(node["fills"], list) and len(node["fills"]) > 0:
                        fill = node["fills"][0]
                        if isinstance(fill, dict) and fill.get("type") == "SOLID" and "color" in fill:
                            c = fill["color"]
                            if isinstance(c, dict):
                                r = int(c.get('r', 0) * 255)
                                g = int(c.get('g', 0) * 255)
                                b = int(c.get('b', 0) * 255)
                                a = c.get('a', 1)
                                frame_info["textColor"] = f"rgba({r}, {g}, {b}, {a})"
                except (TypeError, ValueError, KeyError) as e:
                    logger.warning(f"Error parsing text style: {e}")
        
        # Extract image information
        if "fills" in node and isinstance(node["fills"], list):
            for fill in node["fills"]:
                if isinstance(fill, dict) and fill.get("type") == "IMAGE":
                    frame_info["hasImage"] = True
                    if "imageRef" in fill:
                        frame_info["imageRef"] = fill["imageRef"]
                    break
        
        # Recursively extract children
        if "children" in node and isinstance(node["children"], list) and len(node["children"]) > 0:
            frame_info["children"] = []
            for child in node["children"]:
                try:
                    child_info = extract_frame_info(child)
                    if child_info:
                        frame_info["children"].append(child_info)
                except Exception as e:
                    logger.warning(f"Error extracting child node: {e}")
                    continue
        
        return frame_info
    
    except Exception as e:
        logger.error(f"Error in extract_frame_info: {e}", exc_info=True)
        return None


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
    tools=[send_progress_update, fetch_figma_design],
    deps_type=AgentDeps,
    system_prompt="""You are an AI assistant that helps users create and edit email templates using the Beefree SDK.

You have access to powerful tools through the Beefree MCP server that allow you to:
- Add and modify sections (rows) with columns
- Add content blocks like titles, paragraphs, images, buttons, social icons, etc.
- Manage templates and validate designs
- Set email metadata and styles
- Send progress updates to keep the user informed
- Fetch designs from Figma and recreate them as email templates

When a user provides a Figma URL, you can:
1. Use the fetch_figma_design tool to retrieve the design data
2. If the tool returns an error (check for "error" key in the response), STOP and inform the user about the specific issue:
   - If it's a token error, tell them to add FIGMA_TOKEN to .env
   - If it's a 403 error, the token is invalid
   - If it's a 404 error, the file URL is wrong or they don't have access
   - If it's another error, explain what went wrong
3. If successful, analyze the structure, colors, typography, and layout
4. Recreate the design as an email template using the Beefree tools
5. Match colors, fonts, spacing, and visual hierarchy as closely as possible
6. Adapt the design for email-friendly layouts (responsive, single column for mobile, etc.)

ERROR HANDLING: 
- Always check if a tool response contains an "error" field
- If you encounter an error, explain it clearly to the user and suggest solutions
- DO NOT proceed with template creation if the Figma fetch failed
- Ask the user to fix the issue before retrying

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

    current_task = None
    stop_requested = False

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            if message_data["type"] == "chat":
                user_message = message_data["message"]
                logger.info(f"Received message: {user_message}")

                # Reset stop flag
                stop_requested = False

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
                            # Check if stop was requested
                            if stop_requested:
                                logger.info("Generation stopped by user")
                                await websocket.send_text(
                                    json.dumps({
                                        "type": "complete",
                                        "message": "Generation stopped by user"
                                    })
                                )
                                break
                            
                            await websocket.send_text(
                                json.dumps({"type": "stream", "content": text})
                            )

                    if not stop_requested:
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

            elif message_data["type"] == "stop":
                logger.info("Stop generation requested")
                stop_requested = True
                await websocket.send_text(
                    json.dumps({
                        "type": "complete",
                        "message": "Stopping generation..."
                    })
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
