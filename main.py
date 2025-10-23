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
    """Process tool calls with enhanced error handling for Beefree MCP tools."""
    try:
        result = await call_tool(
            name,
            tool_args,
            {"x-bee-uid": ctx.deps.uid},
        )
        return result
    except Exception as e:
        error_msg = f"Tool '{name}' failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # Send progress update about the failure
        if ctx.deps.websocket and name == "beefree_add_image":
            try:
                await ctx.deps.websocket.send_text(
                    json.dumps({
                        "type": "progress", 
                        "message": f"⚠️ Could not add image - continuing with template..."
                    })
                )
            except:
                pass
        
        # Re-raise the exception so the agent can handle it
        raise


beefree_server = MCPServerStreamableHTTP(
    url="https://api.getbee.io/v1/sdk/mcp",
    headers={
        "Authorization": f"Bearer {settings.beefree_mcp_api_key}",
    },
    process_tool_call=process_tool_call,
    max_retries=3,  # Increase retry count
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


def find_node_by_id(node: dict, target_id: str) -> Optional[dict]:
    """Recursively search for a node by its ID in the Figma tree.
    
    Args:
        node: The current node to search
        target_id: The ID to search for
        
    Returns:
        The node if found, None otherwise
    """
    if not isinstance(node, dict):
        return None
        
    # Check if this is the node we're looking for
    if node.get("id") == target_id:
        return node
    
    # Recursively search children
    if "children" in node and isinstance(node["children"], list):
        for child in node["children"]:
            result = find_node_by_id(child, target_id)
            if result:
                return result
    
    return None


async def fetch_figma_design(
    ctx: RunContext[AgentDeps], figma_url: str
) -> str:
    """Fetch design data from Figma API.

    Args:
        ctx: The run context containing dependencies
        figma_url: The Figma file URL with optional node ID (e.g., https://www.figma.com/file/FILE_KEY/...?node-id=123-456)

    Returns:
        A JSON string containing the Figma design data including:
        - document structure
        - components and their properties
        - styles (colors, typography)
        - layout information
        - text content
        
        If a node-id is provided in the URL, only that specific frame/component will be returned.
    """
    await send_progress_update(ctx, "Fetching design from Figma...")
    
    try:
        # Validate Figma token exists
        if not settings.figma_token or settings.figma_token == "your_figma_access_token":
            error_msg = "Figma token not configured. Please add FIGMA_TOKEN to your .env file."
            logger.error(error_msg)
            await send_progress_update(ctx, f"❌ {error_msg}")
            return json.dumps({"error": error_msg})
        
        # Extract file key and node ID from Figma URL
        # URL format: https://www.figma.com/file/{file_key}/{title}?node-id=123-456
        # or https://www.figma.com/design/{file_key}/{title}?node-id=123-456
        import re
        from urllib.parse import urlparse, parse_qs
        
        match = re.search(r'/(file|design)/([a-zA-Z0-9]+)', figma_url)
        if not match:
            error_msg = "Invalid Figma URL. Expected format: https://www.figma.com/file/FILE_KEY/... or https://www.figma.com/design/FILE_KEY/..."
            logger.error(error_msg)
            await send_progress_update(ctx, f"❌ {error_msg}")
            return json.dumps({"error": error_msg})
        
        file_key = match.group(2)
        
        # Extract node ID if present (format: node-id=123-456 or node-id=123:456)
        node_id = None
        parsed_url = urlparse(figma_url)
        query_params = parse_qs(parsed_url.query)
        if 'node-id' in query_params:
            # Convert Figma URL format (123-456) to API format (123:456)
            node_id = query_params['node-id'][0].replace('-', ':')
            logger.info(f"Extracted node ID: {node_id}")
            await send_progress_update(ctx, f"📥 Fetching specific frame from Figma file: {file_key} (node: {node_id})")
        else:
            logger.info(f"No node ID found, fetching entire file: {file_key}")
            await send_progress_update(ctx, f"📥 Fetching Figma file: {file_key}")
        
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
            
            logger.info(f"Successfully fetched Figma file: {figma_data.get('name', 'Unknown')} (key: {file_key})")
            await send_progress_update(ctx, f"Successfully retrieved Figma design: {figma_data.get('name', 'Unknown')}. Analyzing structure...")
            
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
            
            # If a specific node ID is provided, find and extract only that node
            if node_id:
                await send_progress_update(ctx, f"🎯 Searching for specific node: {node_id}...")
                target_node = find_node_by_id(design_info["document"], node_id)
                
                if not target_node:
                    error_msg = f"Node {node_id} not found in the Figma file. Please check the URL."
                    logger.error(error_msg)
                    await send_progress_update(ctx, f"❌ {error_msg}")
                    return json.dumps({"error": error_msg})
                
                logger.info(f"Found target node: {target_node.get('name', 'Unnamed')} (type: {target_node.get('type')})")
                await send_progress_update(ctx, f"✅ Found frame: {target_node.get('name', 'Unnamed')}")
                
                # Create simplified structure with only this node
                simplified = {
                    "file_name": design_info["name"],
                    "pages": [{
                        "name": "Selected Frame",
                        "frames": [extract_frame_info(target_node)]
                    }],
                    "color_styles": {},
                    "text_styles": {},
                }
            else:
                # Extract all pages and their content (original behavior)
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
            
            logger.info(f"Extracted {len(simplified['pages'])} pages from Figma file '{simplified['file_name']}'")
            
            # Fetch images if there are any image nodes
            image_node_ids = []
            def collect_image_nodes(node_data):
                """Recursively collect all nodes that have images"""
                if isinstance(node_data, dict):
                    if node_data.get("hasImage") and "id" in node_data:
                        image_node_ids.append(node_data["id"])
                    if "children" in node_data:
                        for child in node_data["children"]:
                            collect_image_nodes(child)
            
            # Collect image node IDs from the raw Figma data
            def collect_image_node_ids_from_raw(node):
                """Collect node IDs that have image fills"""
                node_ids = []
                if isinstance(node, dict):
                    # Check if this node has image fills
                    if "fills" in node and isinstance(node["fills"], list):
                        for fill in node["fills"]:
                            if isinstance(fill, dict) and fill.get("type") == "IMAGE":
                                if "id" in node:
                                    node_ids.append(node["id"])
                                break
                    
                    # Recursively check children
                    if "children" in node and isinstance(node["children"], list):
                        for child in node["children"]:
                            node_ids.extend(collect_image_node_ids_from_raw(child))
                
                return node_ids
            
            # Collect all image node IDs from the document (or specific node)
            all_image_node_ids = []
            if node_id and target_node:
                # Only collect images from the specific node
                all_image_node_ids.extend(collect_image_node_ids_from_raw(target_node))
            elif "children" in design_info["document"]:
                # Collect images from all pages
                for page in design_info["document"]["children"]:
                    all_image_node_ids.extend(collect_image_node_ids_from_raw(page))
            
            # Fetch image URLs if there are any images
            image_urls = {}
            if all_image_node_ids:
                await send_progress_update(ctx, f"🖼️ Fetching {len(all_image_node_ids)} images from Figma...")
                logger.info(f"Fetching images for {len(all_image_node_ids)} nodes")
                
                try:
                    # Fetch image URLs from Figma
                    image_response = await client.get(
                        f"https://api.figma.com/v1/images/{file_key}",
                        params={
                            "ids": ",".join(all_image_node_ids),
                            "format": "png",
                            "scale": 2
                        },
                        headers=headers,
                        timeout=30.0
                    )
                    
                    if image_response.status_code == 200:
                        image_data = image_response.json()
                        image_urls = image_data.get("images", {})
                        logger.info(f"Successfully fetched {len(image_urls)} image URLs")
                        await send_progress_update(ctx, f"✅ Successfully fetched {len(image_urls)} image URLs")
                    else:
                        logger.warning(f"Failed to fetch images: {image_response.status_code}")
                        await send_progress_update(ctx, f"⚠️ Could not fetch images (continuing without them)")
                except Exception as img_error:
                    logger.warning(f"Error fetching images: {img_error}")
                    await send_progress_update(ctx, f"⚠️ Could not fetch images: {str(img_error)}")
            
            # Add image URLs to the simplified structure
            simplified["image_urls"] = image_urls
            
            await send_progress_update(ctx, f"✅ Figma design analysis complete for '{simplified['file_name']}'. Ready to recreate in email template.")
            
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
        Simplified frame information with layout, colors, text, and children, 
        but preserving all original properties for HTML generation
    """
    try:
        if not isinstance(node, dict):
            return None
        
        # Start with a copy of the original node to preserve all properties
        frame_info = node.copy()
        
        # Add some computed properties for convenience
        frame_info["name"] = node.get("name", "Unnamed")
        frame_info["type"] = node.get("type", "UNKNOWN")
        
        # Include node ID for image mapping
        if "id" in node:
            frame_info["id"] = node["id"]
        
        # Safely extract dimensions if not already present
        if "width" not in frame_info or "height" not in frame_info:
            bounding_box = node.get("absoluteBoundingBox", {})
            if isinstance(bounding_box, dict):
                frame_info["width"] = bounding_box.get("width")
                frame_info["height"] = bounding_box.get("height")
                # Also extract position
                frame_info["x"] = bounding_box.get("x", 0)
                frame_info["y"] = bounding_box.get("y", 0)
        
        # Extract background color if not in fills
        if "backgroundColor" in node and "backgroundColor" not in frame_info:
            try:
                bg = node["backgroundColor"]
                if isinstance(bg, dict):
                    r = int(bg.get('r', 0) * 255)
                    g = int(bg.get('g', 0) * 255)
                    b = int(bg.get('b', 0) * 255)
                    a = bg.get('a', 1)
                    frame_info["backgroundColorRGBA"] = f"rgba({r}, {g}, {b}, {a})"
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


def rgb_to_hex(r: float, g: float, b: float) -> str:
    """Convert RGB values (0-1) to hex color."""
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def get_node_styles(node: dict, is_root: bool = False, parent_x: float = 0, parent_y: float = 0) -> dict:
    """Extract ALL CSS styles from a Figma node for maximum fidelity."""
    styles = {}
    
    # Get position from absoluteBoundingBox
    abs_box = node.get("absoluteBoundingBox", {})
    node_x = abs_box.get("x", node.get("x", 0))
    node_y = abs_box.get("y", node.get("y", 0))
    
    # Position - Figma uses absolute positioning, we need relative
    if not is_root:
        styles["position"] = "absolute"
        # Calculate position relative to parent
        rel_x = node_x - parent_x
        rel_y = node_y - parent_y
        styles["left"] = f"{rel_x}px"
        styles["top"] = f"{rel_y}px"
    else:
        # For root frames, use relative positioning
        styles["position"] = "relative"
    
    # Size
    width = abs_box.get("width", node.get("width"))
    height = abs_box.get("height", node.get("height"))
    if width is not None:
        styles["width"] = f"{width}px"
    if height is not None:
        styles["height"] = f"{height}px"
    
    # Min/Max width and height
    if "minWidth" in node and node["minWidth"]:
        styles["min-width"] = f"{node['minWidth']}px"
    if "maxWidth" in node and node["maxWidth"]:
        styles["max-width"] = f"{node['maxWidth']}px"
    if "minHeight" in node and node["minHeight"]:
        styles["min-height"] = f"{node['minHeight']}px"
    if "maxHeight" in node and node["maxHeight"]:
        styles["max-height"] = f"{node['maxHeight']}px"
    
    # Opacity
    if "opacity" in node and node["opacity"] != 1:
        styles["opacity"] = str(node["opacity"])
    
    # Blend mode
    blend_mode = node.get("blendMode")
    if blend_mode and blend_mode != "NORMAL":
        blend_map = {
            "MULTIPLY": "multiply",
            "SCREEN": "screen",
            "OVERLAY": "overlay",
            "DARKEN": "darken",
            "LIGHTEN": "lighten",
            "COLOR_DODGE": "color-dodge",
            "COLOR_BURN": "color-burn",
            "HARD_LIGHT": "hard-light",
            "SOFT_LIGHT": "soft-light",
            "DIFFERENCE": "difference",
            "EXCLUSION": "exclusion",
            "HUE": "hue",
            "SATURATION": "saturation",
            "COLOR": "color",
            "LUMINOSITY": "luminosity"
        }
        if blend_mode in blend_map:
            styles["mix-blend-mode"] = blend_map[blend_mode]
    
    # Visibility
    if node.get("visible") == False:
        styles["display"] = "none"
    
    # Background color and fills (but NOT for text nodes - text uses fills for color)
    node_type = node.get("type", "")
    if node_type != "TEXT" and "fills" in node and isinstance(node["fills"], list):
        visible_fills = [f for f in node["fills"] if isinstance(f, dict) and f.get("visible", True)]
        if visible_fills:
            fill = visible_fills[0]  # Use first visible fill
            fill_type = fill.get("type")
            
            if fill_type == "SOLID":
                color = fill.get("color", {})
                if color:
                    r = color.get("r", 0)
                    g = color.get("g", 0)
                    b = color.get("b", 0)
                    alpha = color.get("a", 1) * fill.get("opacity", 1)
                    if alpha < 1:
                        styles["background-color"] = f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {alpha})"
                    else:
                        hex_color = rgb_to_hex(r, g, b)
                        styles["background-color"] = hex_color
            
            elif fill_type == "GRADIENT_LINEAR":
                # Linear gradient
                gradient_stops = fill.get("gradientStops", [])
                if gradient_stops:
                    stops = []
                    for stop in gradient_stops:
                        color = stop.get("color", {})
                        position = stop.get("position", 0) * 100
                        r = int(color.get("r", 0) * 255)
                        g = int(color.get("g", 0) * 255)
                        b = int(color.get("b", 0) * 255)
                        a = color.get("a", 1)
                        stops.append(f"rgba({r}, {g}, {b}, {a}) {position}%")
                    
                    # Calculate angle from gradient handles
                    handles = fill.get("gradientHandlePositions", [])
                    angle = 90  # Default
                    if len(handles) >= 2:
                        dx = handles[1].get("x", 1) - handles[0].get("x", 0)
                        dy = handles[1].get("y", 0) - handles[0].get("y", 0)
                        import math
                        angle = math.degrees(math.atan2(dy, dx)) + 90
                    
                    styles["background"] = f"linear-gradient({angle}deg, {', '.join(stops)})"
    
    # Alternative: backgroundColor property (for frames, but NOT for text)
    elif node_type != "TEXT" and "backgroundColor" in node and node.get("visible", True):
        bg = node["backgroundColor"]
        if isinstance(bg, dict):
            r = bg.get("r", 0)
            g = bg.get("g", 0)
            b = bg.get("b", 0)
            a = bg.get("a", 1)
            if a < 1:
                styles["background-color"] = f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {a})"
            else:
                styles["background-color"] = rgb_to_hex(r, g, b)
    
    # Strokes (borders)
    if "strokes" in node and isinstance(node["strokes"], list):
        visible_strokes = [s for s in node["strokes"] if isinstance(s, dict) and s.get("visible", True)]
        if visible_strokes:
            stroke = visible_strokes[0]
            if stroke.get("type") == "SOLID":
                color = stroke.get("color", {})
                stroke_weight = node.get("strokeWeight", 1)
                stroke_align = node.get("strokeAlign", "INSIDE")
                
                r = color.get("r", 0)
                g = color.get("g", 0)
                b = color.get("b", 0)
                alpha = color.get("a", 1) * stroke.get("opacity", 1)
                
                if alpha < 1:
                    color_str = f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {alpha})"
                else:
                    color_str = rgb_to_hex(r, g, b)
                
                styles["border"] = f"{stroke_weight}px solid {color_str}"
                
                # Adjust for stroke alignment
                if stroke_align == "OUTSIDE":
                    styles["box-sizing"] = "content-box"
                elif stroke_align == "CENTER":
                    styles["box-sizing"] = "border-box"
                else:  # INSIDE
                    styles["box-sizing"] = "border-box"
    
    # Individual stroke weights
    if "strokeTopWeight" in node and "strokeRightWeight" in node:
        styles["border-top-width"] = f"{node.get('strokeTopWeight', 0)}px"
        styles["border-right-width"] = f"{node.get('strokeRightWeight', 0)}px"
        styles["border-bottom-width"] = f"{node.get('strokeBottomWeight', 0)}px"
        styles["border-left-width"] = f"{node.get('strokeLeftWeight', 0)}px"
    
    # Corner radius
    corner_radius = node.get("cornerRadius")
    if corner_radius and corner_radius > 0:
        styles["border-radius"] = f"{corner_radius}px"
    
    # Individual corner radii
    if "rectangleCornerRadii" in node:
        radii = node["rectangleCornerRadii"]
        if isinstance(radii, list) and len(radii) == 4:
            styles["border-radius"] = f"{radii[0]}px {radii[1]}px {radii[2]}px {radii[3]}px"
    
    # Effects (shadows, blurs)
    if "effects" in node and isinstance(node["effects"], list):
        shadows = []
        for effect in node["effects"]:
            if not isinstance(effect, dict) or not effect.get("visible", True):
                continue
            
            effect_type = effect.get("type")
            if effect_type in ["DROP_SHADOW", "INNER_SHADOW"]:
                offset_x = effect.get("offset", {}).get("x", 0)
                offset_y = effect.get("offset", {}).get("y", 0)
                radius = effect.get("radius", 0)
                spread = effect.get("spread", 0) if effect_type == "DROP_SHADOW" else 0
                color = effect.get("color", {})
                r = int(color.get("r", 0) * 255)
                g = int(color.get("g", 0) * 255)
                b = int(color.get("b", 0) * 255)
                a = color.get("a", 1)
                
                shadow = f"{'inset ' if effect_type == 'INNER_SHADOW' else ''}{offset_x}px {offset_y}px {radius}px {spread}px rgba({r}, {g}, {b}, {a})"
                shadows.append(shadow)
            
            elif effect_type == "LAYER_BLUR":
                blur_radius = effect.get("radius", 0)
                styles["filter"] = f"blur({blur_radius}px)"
            
            elif effect_type == "BACKGROUND_BLUR":
                blur_radius = effect.get("radius", 0)
                styles["backdrop-filter"] = f"blur({blur_radius}px)"
        
        if shadows:
            styles["box-shadow"] = ", ".join(shadows)
    
    # Layout constraints (flexbox, padding, etc.)
    layout_mode = node.get("layoutMode")
    if layout_mode:
        styles["display"] = "flex"
        if layout_mode == "HORIZONTAL":
            styles["flex-direction"] = "row"
        elif layout_mode == "VERTICAL":
            styles["flex-direction"] = "column"
        
        # Padding
        padding_top = node.get("paddingTop", 0)
        padding_right = node.get("paddingRight", 0)
        padding_bottom = node.get("paddingBottom", 0)
        padding_left = node.get("paddingLeft", 0)
        if any([padding_top, padding_right, padding_bottom, padding_left]):
            styles["padding"] = f"{padding_top}px {padding_right}px {padding_bottom}px {padding_left}px"
        
        # Gap
        item_spacing = node.get("itemSpacing", 0)
        if item_spacing > 0:
            styles["gap"] = f"{item_spacing}px"
        
        # Alignment
        primary_axis_align = node.get("primaryAxisAlignItems")
        if primary_axis_align:
            align_map = {
                "MIN": "flex-start",
                "CENTER": "center",
                "MAX": "flex-end",
                "SPACE_BETWEEN": "space-between"
            }
            styles["justify-content"] = align_map.get(primary_axis_align, "flex-start")
        
        counter_axis_align = node.get("counterAxisAlignItems")
        if counter_axis_align:
            align_map = {
                "MIN": "flex-start",
                "CENTER": "center",
                "MAX": "flex-end",
                "BASELINE": "baseline"
            }
            styles["align-items"] = align_map.get(counter_axis_align, "flex-start")
        
        # Flex wrap
        layout_wrap = node.get("layoutWrap")
        if layout_wrap == "WRAP":
            styles["flex-wrap"] = "wrap"
        
        # For auto-layout frames, don't use absolute positioning for children
        if not is_root:
            styles["position"] = "relative"
            if "left" in styles:
                del styles["left"]
            if "top" in styles:
                del styles["top"]
    
    # Layout sizing (grow/shrink)
    layout_grow = node.get("layoutGrow")
    if layout_grow == 1:
        styles["flex-grow"] = "1"
    
    layout_align = node.get("layoutAlign")
    if layout_align == "STRETCH":
        styles["align-self"] = "stretch"
    
    # Clipping
    if node.get("clipsContent"):
        styles["overflow"] = "hidden"
    
    # Text styles
    if node.get("type") == "TEXT":
        style_info = node.get("style", {})
        
        # Font size
        if "fontSize" in style_info:
            styles["font-size"] = f"{style_info['fontSize']}px"
        
        # Font family
        if "fontFamily" in style_info:
            styles["font-family"] = f"'{style_info['fontFamily']}', sans-serif"
        
        # Font weight
        if "fontWeight" in style_info:
            styles["font-weight"] = str(style_info["fontWeight"])
        
        # Font style (italic)
        if "italic" in style_info and style_info["italic"]:
            styles["font-style"] = "italic"
        
        # Text alignment
        if "textAlignHorizontal" in style_info:
            align = style_info["textAlignHorizontal"].lower()
            align_map = {"left": "left", "center": "center", "right": "right", "justified": "justify"}
            styles["text-align"] = align_map.get(align, "left")
        
        if "textAlignVertical" in style_info:
            valign = style_info["textAlignVertical"].lower()
            if valign == "center":
                styles["display"] = "flex"
                styles["align-items"] = "center"
            elif valign == "bottom":
                styles["display"] = "flex"
                styles["align-items"] = "flex-end"
        
        # Line height
        if "lineHeightPx" in style_info:
            styles["line-height"] = f"{style_info['lineHeightPx']}px"
        elif "lineHeightPercent" in style_info:
            styles["line-height"] = f"{style_info['lineHeightPercent']}%"
        elif "lineHeightUnit" in style_info and style_info["lineHeightUnit"] == "AUTO":
            styles["line-height"] = "normal"
        
        # Letter spacing
        if "letterSpacing" in style_info:
            styles["letter-spacing"] = f"{style_info['letterSpacing']}px"
        
        # Paragraph spacing
        if "paragraphSpacing" in style_info and style_info["paragraphSpacing"] > 0:
            styles["margin-bottom"] = f"{style_info['paragraphSpacing']}px"
        
        # Paragraph indent
        if "paragraphIndent" in style_info and style_info["paragraphIndent"] > 0:
            styles["text-indent"] = f"{style_info['paragraphIndent']}px"
        
        # Text transform
        if "textCase" in style_info:
            text_case = style_info["textCase"]
            case_map = {
                "UPPER": "uppercase",
                "LOWER": "lowercase",
                "TITLE": "capitalize",
                "SMALL_CAPS": "small-caps"
            }
            if text_case in case_map:
                if text_case == "SMALL_CAPS":
                    styles["font-variant"] = "small-caps"
                else:
                    styles["text-transform"] = case_map[text_case]
        
        # Text decoration
        if "textDecoration" in style_info:
            text_dec = style_info["textDecoration"]
            dec_map = {
                "UNDERLINE": "underline",
                "STRIKETHROUGH": "line-through"
            }
            styles["text-decoration"] = dec_map.get(text_dec, "none")
        
        # Text color from fills
        if "fills" in node and isinstance(node["fills"], list):
            for fill in node["fills"]:
                if isinstance(fill, dict) and fill.get("type") == "SOLID" and fill.get("visible", True):
                    color = fill.get("color", {})
                    if color:
                        r = color.get("r", 0)
                        g = color.get("g", 0)
                        b = color.get("b", 0)
                        alpha = color.get("a", 1) * fill.get("opacity", 1)
                        if alpha < 1:
                            styles["color"] = f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {alpha})"
                        else:
                            hex_color = rgb_to_hex(r, g, b)
                            styles["color"] = hex_color
                    break
        
        # Text shadow from effects
        if "effects" in node:
            text_shadows = []
            for effect in node["effects"]:
                if isinstance(effect, dict) and effect.get("visible", True) and effect.get("type") == "DROP_SHADOW":
                    offset_x = effect.get("offset", {}).get("x", 0)
                    offset_y = effect.get("offset", {}).get("y", 0)
                    radius = effect.get("radius", 0)
                    color = effect.get("color", {})
                    r = int(color.get("r", 0) * 255)
                    g = int(color.get("g", 0) * 255)
                    b = int(color.get("b", 0) * 255)
                    a = color.get("a", 1)
                    text_shadows.append(f"{offset_x}px {offset_y}px {radius}px rgba({r}, {g}, {b}, {a})")
            
            if text_shadows:
                styles["text-shadow"] = ", ".join(text_shadows)
        
        # White space handling for text
        styles["white-space"] = "pre-wrap"
        styles["word-wrap"] = "break-word"
        
        # Text overflow
        text_auto_resize = node.get("textAutoResize")
        if text_auto_resize == "TRUNCATE":
            styles["overflow"] = "hidden"
            styles["text-overflow"] = "ellipsis"
            styles["white-space"] = "nowrap"
    
    # Rotation
    if "rotation" in node and node["rotation"] != 0:
        styles["transform"] = f"rotate({node['rotation']}deg)"
    
    return styles
    
    # Get position from absoluteBoundingBox
    abs_box = node.get("absoluteBoundingBox", {})
    node_x = abs_box.get("x", node.get("x", 0))
    node_y = abs_box.get("y", node.get("y", 0))
    
    # Position - Figma uses absolute positioning, we need relative
    if not is_root:
        styles["position"] = "absolute"
        # Calculate position relative to parent
        rel_x = node_x - parent_x
        rel_y = node_y - parent_y
        styles["left"] = f"{int(rel_x)}px"
        styles["top"] = f"{int(rel_y)}px"
    else:
        # For root frames, use relative positioning
        styles["position"] = "relative"
    
    # Size
    width = abs_box.get("width", node.get("width"))
    height = abs_box.get("height", node.get("height"))
    if width is not None and height is not None:
        styles["width"] = f"{int(width)}px"
        styles["height"] = f"{int(height)}px"
    
    # Opacity
    if "opacity" in node and node["opacity"] != 1:
        styles["opacity"] = str(node["opacity"])
    
    # Background color from fills
    if "fills" in node and isinstance(node["fills"], list):
        for fill in node["fills"]:
            if isinstance(fill, dict) and fill.get("visible", True):
                if fill.get("type") == "SOLID":
                    color = fill.get("color", {})
                    if color:
                        r = color.get("r", 0)
                        g = color.get("g", 0)
                        b = color.get("b", 0)
                        alpha = color.get("a", 1)
                        if alpha < 1:
                            styles["background-color"] = f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {alpha})"
                        else:
                            hex_color = rgb_to_hex(r, g, b)
                            styles["background-color"] = hex_color
                    break
    
    # Border/Stroke
    if "strokes" in node and isinstance(node["strokes"], list) and len(node["strokes"]) > 0:
        stroke = node["strokes"][0]
        if isinstance(stroke, dict) and stroke.get("visible", True) and stroke.get("type") == "SOLID":
            color = stroke.get("color", {})
            stroke_weight = node.get("strokeWeight", 1)
            hex_color = rgb_to_hex(
                color.get("r", 0),
                color.get("g", 0),
                color.get("b", 0)
            )
            styles["border"] = f"{stroke_weight}px solid {hex_color}"
    
    # Corner radius
    corner_radius = node.get("cornerRadius")
    if corner_radius and corner_radius > 0:
        styles["border-radius"] = f"{int(corner_radius)}px"
    
    # Layout constraints (flexbox, padding, etc.)
    layout_mode = node.get("layoutMode")
    if layout_mode:
        styles["display"] = "flex"
        if layout_mode == "HORIZONTAL":
            styles["flex-direction"] = "row"
        elif layout_mode == "VERTICAL":
            styles["flex-direction"] = "column"
        
        # Padding
        padding_top = node.get("paddingTop", 0)
        padding_right = node.get("paddingRight", 0)
        padding_bottom = node.get("paddingBottom", 0)
        padding_left = node.get("paddingLeft", 0)
        if any([padding_top, padding_right, padding_bottom, padding_left]):
            styles["padding"] = f"{int(padding_top)}px {int(padding_right)}px {int(padding_bottom)}px {int(padding_left)}px"
        
        # Gap
        item_spacing = node.get("itemSpacing", 0)
        if item_spacing > 0:
            styles["gap"] = f"{int(item_spacing)}px"
        
        # Alignment
        primary_axis_align = node.get("primaryAxisAlignItems")
        if primary_axis_align:
            align_map = {
                "MIN": "flex-start",
                "CENTER": "center",
                "MAX": "flex-end",
                "SPACE_BETWEEN": "space-between"
            }
            styles["justify-content"] = align_map.get(primary_axis_align, "flex-start")
        
        counter_axis_align = node.get("counterAxisAlignItems")
        if counter_axis_align:
            align_map = {
                "MIN": "flex-start",
                "CENTER": "center",
                "MAX": "flex-end"
            }
            styles["align-items"] = align_map.get(counter_axis_align, "flex-start")
        
        # For auto-layout frames, don't use absolute positioning for children
        # Override position for direct children to be relative
        if not is_root:
            styles["position"] = "relative"
            if "left" in styles:
                del styles["left"]
            if "top" in styles:
                del styles["top"]
    
    # Text styles
    if node.get("type") == "TEXT":
        style_info = node.get("style", {})
        
        # Font size
        if "fontSize" in style_info:
            styles["font-size"] = f"{style_info['fontSize']}px"
        
        # Font family
        if "fontFamily" in style_info:
            styles["font-family"] = f"'{style_info['fontFamily']}', sans-serif"
        
        # Font weight
        if "fontWeight" in style_info:
            styles["font-weight"] = str(style_info["fontWeight"])
        
        # Text alignment
        if "textAlignHorizontal" in style_info:
            align = style_info["textAlignHorizontal"].lower()
            if align in ["left", "center", "right", "justified"]:
                styles["text-align"] = align if align != "justified" else "justify"
        
        # Line height
        if "lineHeightPx" in style_info:
            styles["line-height"] = f"{style_info['lineHeightPx']}px"
        elif "lineHeightPercent" in style_info:
            styles["line-height"] = f"{style_info['lineHeightPercent']}%"
        
        # Letter spacing
        if "letterSpacing" in style_info:
            styles["letter-spacing"] = f"{style_info['letterSpacing']}px"
        
        # Text transform
        if "textCase" in style_info:
            text_case = style_info["textCase"]
            if text_case == "UPPER":
                styles["text-transform"] = "uppercase"
            elif text_case == "LOWER":
                styles["text-transform"] = "lowercase"
            elif text_case == "TITLE":
                styles["text-transform"] = "capitalize"
        
        # Text decoration
        if "textDecoration" in style_info:
            text_dec = style_info["textDecoration"]
            if text_dec == "UNDERLINE":
                styles["text-decoration"] = "underline"
            elif text_dec == "STRIKETHROUGH":
                styles["text-decoration"] = "line-through"
        
        # Text color from fills
        if "fills" in node and isinstance(node["fills"], list):
            for fill in node["fills"]:
                if isinstance(fill, dict) and fill.get("type") == "SOLID" and fill.get("visible", True):
                    color = fill.get("color", {})
                    if color:
                        r = color.get("r", 0)
                        g = color.get("g", 0)
                        b = color.get("b", 0)
                        alpha = color.get("a", 1)
                        if alpha < 1:
                            styles["color"] = f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {alpha})"
                        else:
                            hex_color = rgb_to_hex(r, g, b)
                            styles["color"] = hex_color
                    break
        
        # White space handling for text
        styles["white-space"] = "pre-wrap"
        styles["word-wrap"] = "break-word"
    
    return styles


def node_to_html(node: dict, image_urls: dict, indent: str = "", is_root: bool = False, parent_x: float = 0, parent_y: float = 0, parent_has_layout: bool = False) -> str:
    """Convert a Figma node to HTML."""
    html = ""
    styles = get_node_styles(node, is_root, parent_x, parent_y)
    
    # If parent has auto-layout, children don't need absolute positioning
    if parent_has_layout and not is_root:
        styles.pop("position", None)
        styles.pop("left", None)
        styles.pop("top", None)
    
    style_str = "; ".join([f"{k}: {v}" for k, v in styles.items()])
    class_name = node.get("name", "unnamed").replace(" ", "-").replace("/", "-").lower()
    node_type = node.get("type", "")
    node_id = node.get("id", "")
    
    # Get current node position for children
    abs_box = node.get("absoluteBoundingBox", {})
    current_x = abs_box.get("x", node.get("x", 0))
    current_y = abs_box.get("y", node.get("y", 0))
    
    # Check if this node has auto-layout
    has_layout = node.get("layoutMode") is not None
    
    # Text node
    if node_type == "TEXT":
        text = node.get("characters", "")
        # Escape HTML special characters
        import html as html_module
        text = html_module.escape(text)
        html += f'{indent}<div class="{class_name}" style="{style_str}">{text}</div>\n'
    
    # Image node
    elif node.get("hasImage") and node_id in image_urls:
        image_url = image_urls[node_id]
        html += f'{indent}<img class="{class_name}" src="{image_url}" alt="{node.get("name", "")}" style="{style_str}" />\n'
    
    # Container with children
    elif "children" in node and isinstance(node["children"], list):
        html += f'{indent}<div class="{class_name}" style="{style_str}">\n'
        for child in node["children"]:
            html += node_to_html(child, image_urls, indent + "  ", False, current_x, current_y, has_layout)
        html += f'{indent}</div>\n'
    
    # Simple element
    else:
        html += f'{indent}<div class="{class_name}" style="{style_str}"></div>\n'
    
    return html


def generate_html_from_figma(figma_data: dict) -> str:
    pages = figma_data.get("pages", [])
    image_urls = figma_data.get("image_urls", {})
    file_name = figma_data.get("file_name", "Figma Design")
    
    body_content = ""
    
    # Process all frames from all pages
    for page in pages:
        frames = page.get("frames", [])
        for frame in frames:
            body_content += node_to_html(frame, image_urls, "    ", True)
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{file_name}</title>
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Helvetica Neue', sans-serif;
      background-color: #f5f5f5;
      padding: 20px;
      margin: 0;
    }}
    img {{
      display: block;
      max-width: 100%;
      height: auto;
    }}
  </style>
</head>
<body>
{body_content}
</body>
</html>"""
    
    return html


async def convert_figma_to_html(
    ctx: RunContext[AgentDeps], figma_url: str
) -> str:
    """Fetch Figma design, convert to HTML, and provide instructions for template creation.
    
    Args:
        ctx: The run context containing dependencies
        figma_url: The Figma file URL
        
    Returns:
        A JSON string containing HTML and template creation instructions
    """
    await send_progress_update(ctx, "🔄 Converting Figma design to HTML...")
    
    # First fetch the Figma design
    figma_json = await fetch_figma_design(ctx, figma_url)
    
    try:
        figma_data = json.loads(figma_json)
        
        # Check for errors
        if "error" in figma_data:
            return figma_json  # Return the error
        
        # Generate HTML from the Figma data
        html_content = generate_html_from_figma(figma_data)
        
        logger.info(f"Generated HTML with {len(html_content)} characters")
        await send_progress_update(ctx, "✅ Successfully converted Figma design to HTML. Analyzing structure for template creation...")
        
        # Return both HTML and design data for template creation
        return json.dumps({
            "html": html_content,
            "figma_data": figma_data,
            "file_name": figma_data.get("file_name", "Figma Design"),
            "instructions": "The HTML represents the structure and styling from Figma. Analyze it to understand the layout hierarchy, then recreate it in Beefree using the appropriate tools (sections, columns, text blocks, images, buttons, etc.)."
        }, indent=2)
        
    except Exception as e:
        error_msg = f"Failed to convert Figma to HTML: {str(e)}"
        logger.error(error_msg, exc_info=True)
        await send_progress_update(ctx, f"❌ {error_msg}")
        return json.dumps({"error": error_msg})


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
    tools=[send_progress_update, fetch_figma_design, convert_figma_to_html],
    deps_type=AgentDeps,
    system_prompt="""You are an AI assistant that helps users create and edit email templates using the Beefree SDK.

You have access to powerful tools through the Beefree MCP server that allow you to:
- Add and modify sections (rows) with columns
- Add content blocks like titles, paragraphs, images, buttons, social icons, etc.
- Manage templates and validate designs
- Set email metadata and styles
- Send progress updates to keep the user informed
- Fetch designs from Figma and recreate them as email templates

When a user provides a Figma URL:
1. Use convert_figma_to_html tool with the Figma URL
2. This tool will:
   - Fetch the Figma design data
   - Convert all nodes to HTML with inline styles
   - Return the HTML structure for analysis
3. Analyze the HTML to understand the exact layout hierarchy
4. Recreate the design in Beefree following the HTML structure
5. This approach better preserves the visual hierarchy and styling

For images:
- Use always the function figma_to_html_endpoint

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
- "Make it look professional" -> Send progress updates as you apply styling and layout""",
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

                # Check if this is a Figma import request - if so, start fresh
                is_figma_request = "figma.com" in user_message.lower() or "import" in user_message.lower() and "figma" in user_message.lower()
                if is_figma_request:
                    logger.info("Detected Figma import request - starting with fresh context")

                # Send start of processing
                await websocket.send_text(
                    json.dumps(
                        {"type": "start", "message": "Processing your request..."}
                    )
                )

                try:
                    # Use empty message history for Figma requests to avoid reusing cached data
                    run_kwargs = {
                        "user_prompt": user_message,
                        "deps": AgentDeps(uid=settings.beefree_uid, websocket=websocket),
                    }
                    
                    if is_figma_request:
                        run_kwargs["message_history"] = []
                    
                    async with agent.run_stream(**run_kwargs) as result:
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


@app.post("/api/figma-to-html")
async def figma_to_html_endpoint(request: dict):
    """Convert Figma design to HTML preview"""
    try:
        figma_url = request.get("figma_url")
        if not figma_url:
            raise HTTPException(status_code=400, detail="figma_url is required")
        
        # Validate Figma token
        if not settings.figma_token or settings.figma_token == "your_figma_access_token":
            raise HTTPException(
                status_code=500,
                detail="Figma token not configured. Please add FIGMA_TOKEN to your .env file"
            )
        
        # Extract file key and node ID from URL
        import re
        from urllib.parse import urlparse, parse_qs
        
        match = re.search(r'/(file|design)/([a-zA-Z0-9]+)', figma_url)
        if not match:
            raise HTTPException(
                status_code=400,
                detail="Invalid Figma URL format"
            )
        
        file_key = match.group(2)
        
        # Extract node ID if present
        node_id = None
        parsed_url = urlparse(figma_url)
        query_params = parse_qs(parsed_url.query)
        if 'node-id' in query_params:
            node_id = query_params['node-id'][0].replace('-', ':')
            logger.info(f"Converting specific node to HTML: {file_key} (node: {node_id})")
        else:
            logger.info(f"Converting Figma file to HTML: {file_key}")
        
        # Fetch Figma data
        async with httpx.AsyncClient() as client:
            headers = {"X-Figma-Token": settings.figma_token}
            
            # Get file data
            response = await client.get(
                f"https://api.figma.com/v1/files/{file_key}",
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Figma API error: {response.text}"
                )
            
            figma_data = response.json()
            
            # Extract design info
            design_info = {
                "name": figma_data.get("name", "Untitled"),
                "document": figma_data.get("document", {}),
            }
            
            # If a specific node ID is provided, find and use only that node
            target_node = None
            if node_id:
                target_node = find_node_by_id(design_info["document"], node_id)
                if not target_node:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Node {node_id} not found in the Figma file"
                    )
                logger.info(f"Found target node: {target_node.get('name', 'Unnamed')} (type: {target_node.get('type')})")
            
            # Simplify structure
            simplified = {
                "file_name": design_info["name"],
                "pages": [],
                "image_urls": {},
            }
            
            # Extract pages or specific node
            if target_node:
                # Only process the specific node
                simplified["pages"] = [{
                    "name": "Selected Frame",
                    "frames": [extract_frame_info(target_node)]
                }]
            elif "children" in design_info["document"]:
                # Process all pages
                for page in design_info["document"]["children"]:
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
                                logger.warning(f"Error extracting frame: {e}")
                    
                    simplified["pages"].append(page_info)
            
            # Collect image node IDs
            def collect_image_node_ids(node):
                node_ids = []
                if isinstance(node, dict):
                    if "fills" in node and isinstance(node["fills"], list):
                        for fill in node["fills"]:
                            if isinstance(fill, dict) and fill.get("type") == "IMAGE":
                                if "id" in node:
                                    node_ids.append(node["id"])
                                break
                    
                    if "children" in node and isinstance(node["children"], list):
                        for child in node["children"]:
                            node_ids.extend(collect_image_node_ids(child))
                
                return node_ids
            
            # Collect all image node IDs from target node or entire document
            all_image_node_ids = []
            if target_node:
                # Only collect images from the specific node
                all_image_node_ids.extend(collect_image_node_ids(target_node))
            elif "children" in design_info["document"]:
                # Collect images from all pages
                for page in design_info["document"]["children"]:
                    all_image_node_ids.extend(collect_image_node_ids(page))
            
            # Fetch image URLs if any
            if all_image_node_ids:
                try:
                    image_response = await client.get(
                        f"https://api.figma.com/v1/images/{file_key}",
                        params={
                            "ids": ",".join(all_image_node_ids),
                            "format": "png",
                            "scale": 2
                        },
                        headers=headers,
                        timeout=30.0
                    )
                    
                    if image_response.status_code == 200:
                        image_data = image_response.json()
                        simplified["image_urls"] = image_data.get("images", {})
                except Exception as img_error:
                    logger.warning(f"Could not fetch images: {img_error}")
            
            # Generate HTML
            html_content = generate_html_from_figma(simplified)
            
            return {
                "html": html_content,
                "file_name": simplified["file_name"],
                "status": "success"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error converting Figma to HTML: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to convert Figma design: {str(e)}"
        )


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
