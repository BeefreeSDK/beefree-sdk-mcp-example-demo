// Show the plugin UI
figma.showUI(__html__, { width: 400, height: 500 });

// Store for image URLs - will be populated when exporting
const imageUrlMap = new Map<string, string>();

// Helper function to convert RGB to hex
function rgbToHex(r: number, g: number, b: number): string {
  const toHex = (n: number) => {
    const hex = Math.round(n * 255).toString(16);
    return hex.length === 1 ? '0' + hex : hex;
  };
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

// Helper function to get CSS styles from a node
function getNodeStyles(node: SceneNode, isRoot: boolean = false): string {
  let styles: string[] = [];

  // Position and size
  if ('width' in node && 'height' in node) {
    styles.push(`width: ${Math.round(node.width)}px`);
    
    // Only set fixed height if not using auto-layout
    if (!('layoutMode' in node) || node.layoutMode === 'NONE') {
      styles.push(`height: ${Math.round(node.height)}px`);
    } else {
      styles.push(`min-height: ${Math.round(node.height)}px`);
    }
  }

  // Use relative positioning for root elements, avoid absolute positioning for children
  if (isRoot && 'x' in node && 'y' in node) {
    styles.push(`position: relative`);
    styles.push(`margin: ${Math.round(node.y)}px auto 0`);
  }

  // Opacity
  if ('opacity' in node && node.opacity !== 1) {
    styles.push(`opacity: ${node.opacity}`);
  }

  // Rotation
  if ('rotation' in node && node.rotation !== 0) {
    styles.push(`transform: rotate(${node.rotation}deg)`);
  }

  // Text color from fills
  if (node.type === 'TEXT' && 'fills' in node && node.fills !== figma.mixed && Array.isArray(node.fills)) {
    const fills = node.fills as Paint[];
    const solidFill = fills.find(f => f.type === 'SOLID' && f.visible !== false) as SolidPaint | undefined;
    if (solidFill) {
      const color = rgbToHex(solidFill.color.r, solidFill.color.g, solidFill.color.b);
      styles.push(`color: ${color}`);
    }
  }

  // Background/Fill (for non-text elements)
  if (node.type !== 'TEXT' && 'fills' in node && node.fills !== figma.mixed && Array.isArray(node.fills)) {
    const fills = node.fills as Paint[];
    const solidFill = fills.find(f => f.type === 'SOLID' && f.visible !== false) as SolidPaint | undefined;
    if (solidFill) {
      const color = rgbToHex(solidFill.color.r, solidFill.color.g, solidFill.color.b);
      const alpha = solidFill.opacity !== undefined ? solidFill.opacity : 1;
      if (alpha < 1) {
        const alphaHex = Math.round(alpha * 255).toString(16).padStart(2, '0');
        styles.push(`background-color: ${color}${alphaHex}`);
      } else {
        styles.push(`background-color: ${color}`);
      }
    }
  }

  // Border/Stroke
  if ('strokes' in node && Array.isArray(node.strokes) && node.strokes.length > 0) {
    const strokes = node.strokes as Paint[];
    const solidStroke = strokes.find(s => s.type === 'SOLID' && s.visible !== false) as SolidPaint | undefined;
    if (solidStroke && 'strokeWeight' in node && typeof node.strokeWeight === 'number') {
      const color = rgbToHex(solidStroke.color.r, solidStroke.color.g, solidStroke.color.b);
      styles.push(`border: ${node.strokeWeight}px solid ${color}`);
    }
  }

  // Corner radius
  if ('cornerRadius' in node && typeof node.cornerRadius === 'number' && node.cornerRadius > 0) {
    styles.push(`border-radius: ${node.cornerRadius}px`);
  }

  // Text styles
  if (node.type === 'TEXT') {
    try {
      if (typeof node.fontSize === 'number') {
        styles.push(`font-size: ${node.fontSize}px`);
      }
      if (node.fontName !== figma.mixed && typeof node.fontName === 'object') {
        styles.push(`font-family: '${node.fontName.family}', sans-serif`);
        const style = node.fontName.style.toLowerCase();
        styles.push(`font-weight: ${style.includes('bold') ? 'bold' : style.includes('medium') ? '500' : style.includes('light') ? '300' : 'normal'}`);
        styles.push(`font-style: ${style.includes('italic') ? 'italic' : 'normal'}`);
      }
      if (node.textAlignHorizontal) {
        const align = node.textAlignHorizontal.toLowerCase();
        if (align === 'left' || align === 'center' || align === 'right' || align === 'justified') {
          styles.push(`text-align: ${align}`);
        }
      }
      if (typeof node.letterSpacing === 'object' && 'value' in node.letterSpacing) {
        styles.push(`letter-spacing: ${node.letterSpacing.value}px`);
      }
      // Skip line-height - let it use browser defaults unless specifically needed
    } catch (e) {
      // Ignore text property errors
    }
  }

  // Auto Layout (Flexbox)
  if ('layoutMode' in node && node.layoutMode !== 'NONE') {
    styles.push(`display: flex`);
    styles.push(`flex-direction: ${node.layoutMode === 'HORIZONTAL' ? 'row' : 'column'}`);
    styles.push(`gap: ${node.itemSpacing}px`);
    styles.push(`padding: ${node.paddingTop}px ${node.paddingRight}px ${node.paddingBottom}px ${node.paddingLeft}px`);
    
    // Alignment
    if (node.primaryAxisAlignItems === 'CENTER') {
      styles.push(`justify-content: center`);
    } else if (node.primaryAxisAlignItems === 'MAX') {
      styles.push(`justify-content: flex-end`);
    } else if (node.primaryAxisAlignItems === 'SPACE_BETWEEN') {
      styles.push(`justify-content: space-between`);
    }

    if (node.counterAxisAlignItems === 'CENTER') {
      styles.push(`align-items: center`);
    } else if (node.counterAxisAlignItems === 'MAX') {
      styles.push(`align-items: flex-end`);
    }
  }

  return styles.join('; ');
}

// Helper function to check if node has an image fill
function hasImageFill(node: SceneNode): boolean {
  if ('fills' in node && node.fills !== figma.mixed && Array.isArray(node.fills)) {
    const fills = node.fills as Paint[];
    return fills.some(fill => fill.type === 'IMAGE' && fill.visible !== false);
  }
  return false;
}

// Function to convert node to HTML
function nodeToHtml(node: SceneNode, indent: string = '', isRoot: boolean = false): string {
  let html = '';
  const styles = getNodeStyles(node, isRoot);
  const className = node.name.replace(/[^a-zA-Z0-9-_]/g, '-').toLowerCase();

  if (node.type === 'TEXT') {
    try {
      const text = node.characters || '';
      html += `${indent}<div class="${className}" style="${styles}">${text}</div>\n`;
    } catch (e) {
      html += `${indent}<div class="${className}" style="${styles}">Text content</div>\n`;
    }
  } else if (hasImageFill(node)) {
    // Node has an image fill - convert to img tag
    const imageUrl = imageUrlMap.get(node.id) || 'placeholder.jpg';
    html += `${indent}<img class="${className}" src="${imageUrl}" alt="${node.name}" style="${styles}" />\n`;
  } else if ('children' in node) {
    // Container element
    html += `${indent}<div class="${className}" style="${styles}">\n`;
    for (const child of node.children) {
      html += nodeToHtml(child, indent + '  ', false);
    }
    html += `${indent}</div>\n`;
  } else {
    // Single element (rectangle, ellipse, etc.)
    html += `${indent}<div class="${className}" style="${styles}"></div>\n`;
  }

  return html;
}

// Function to generate complete HTML document
function generateHtmlDocument(nodes: readonly SceneNode[]): string {
  let bodyContent = '';
  
  for (const node of nodes) {
    bodyContent += nodeToHtml(node, '    ', true);
  }

  // Add note about embedded images
  const hasImages = imageUrlMap.size > 0;
  const imageNote = hasImages ? `
  <!-- Images are embedded as base64 data URLs for portability -->
` : '';

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Figma Export</title>
  <style>
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Helvetica Neue', sans-serif;
      background-color: #f5f5f5;
      padding: 0;
      margin: 0;
    }
    img {
      display: block;
      object-fit: cover;
    }
  </style>
</head>
<body>${imageNote}
${bodyContent}
</body>
</html>`;
}

// Function to extract properties from a node
function extractNodeProperties(node: SceneNode): any {
  const baseProperties: any = {
    id: node.id,
    name: node.name,
    type: node.type,
    visible: node.visible,
    locked: node.locked,
  };

  // Add position and size for nodes that support it
  if ('x' in node && 'y' in node) {
    baseProperties.x = node.x;
    baseProperties.y = node.y;
  }

  if ('width' in node && 'height' in node) {
    baseProperties.width = node.width;
    baseProperties.height = node.height;
  }

  if ('rotation' in node) {
    baseProperties.rotation = node.rotation;
  }

  if ('opacity' in node) {
    baseProperties.opacity = node.opacity;
  }

  // Extract blend mode
  if ('blendMode' in node) {
    baseProperties.blendMode = node.blendMode;
  }

  // Extract fills
  if ('fills' in node && node.fills !== figma.mixed) {
    baseProperties.fills = (node.fills as ReadonlyArray<Paint>).map(fill => {
      if (fill.type === 'SOLID') {
        return {
          type: fill.type,
          color: fill.color,
          opacity: fill.opacity,
        };
      } else if (fill.type === 'GRADIENT_LINEAR' || fill.type === 'GRADIENT_RADIAL' || fill.type === 'GRADIENT_ANGULAR' || fill.type === 'GRADIENT_DIAMOND') {
        return {
          type: fill.type,
          gradientStops: fill.gradientStops,
          gradientTransform: fill.gradientTransform,
          opacity: fill.opacity,
        };
      } else if (fill.type === 'IMAGE') {
        return {
          type: fill.type,
          scaleMode: fill.scaleMode,
          imageHash: fill.imageHash,
          opacity: fill.opacity,
        };
      }
      return { type: fill.type };
    });
  }

  // Extract strokes
  if ('strokes' in node) {
    baseProperties.strokes = (node.strokes as ReadonlyArray<Paint>).map(stroke => {
      if (stroke.type === 'SOLID') {
        return {
          type: stroke.type,
          color: stroke.color,
          opacity: stroke.opacity,
        };
      }
      return { type: stroke.type };
    });
  }

  if ('strokeWeight' in node) {
    baseProperties.strokeWeight = node.strokeWeight;
  }

  if ('strokeAlign' in node) {
    baseProperties.strokeAlign = node.strokeAlign;
  }

  // Extract corner radius
  if ('cornerRadius' in node) {
    baseProperties.cornerRadius = node.cornerRadius;
  }

  // Extract effects (shadows, blurs)
  if ('effects' in node) {
    baseProperties.effects = node.effects.map(effect => ({
      type: effect.type,
      visible: effect.visible,
      radius: 'radius' in effect ? effect.radius : undefined,
      color: 'color' in effect ? effect.color : undefined,
      offset: 'offset' in effect ? effect.offset : undefined,
      spread: 'spread' in effect ? effect.spread : undefined,
    }));
  }

  // Extract text properties
  if (node.type === 'TEXT') {
    try {
      baseProperties.characters = node.characters;
      baseProperties.fontSize = node.fontSize;
      baseProperties.fontName = node.fontName;
      baseProperties.textAlignHorizontal = node.textAlignHorizontal;
      baseProperties.textAlignVertical = node.textAlignVertical;
      baseProperties.letterSpacing = node.letterSpacing;
      baseProperties.lineHeight = node.lineHeight;
    } catch (e) {
      // Some text properties might not be accessible
      baseProperties.textNote = 'Some text properties require font loading';
    }
  }

  // Extract layout properties (Auto Layout)
  if ('layoutMode' in node && node.layoutMode !== 'NONE') {
    baseProperties.layout = {
      mode: node.layoutMode,
      paddingLeft: node.paddingLeft,
      paddingRight: node.paddingRight,
      paddingTop: node.paddingTop,
      paddingBottom: node.paddingBottom,
      itemSpacing: node.itemSpacing,
      primaryAxisAlignItems: node.primaryAxisAlignItems,
      counterAxisAlignItems: node.counterAxisAlignItems,
    };
  }

  // Extract constraints
  if ('constraints' in node) {
    baseProperties.constraints = node.constraints;
  }

  // Export settings
  if ('exportSettings' in node) {
    baseProperties.exportSettings = node.exportSettings;
  }

  // For container nodes, include children
  if ('children' in node) {
    baseProperties.children = node.children.map(child => extractNodeProperties(child));
  }

  return baseProperties;
}

// Function to collect all nodes with images
function collectImageNodes(nodes: readonly SceneNode[], imageNodes: SceneNode[] = []): SceneNode[] {
  for (const node of nodes) {
    if (hasImageFill(node)) {
      imageNodes.push(node);
    }
    if ('children' in node) {
      collectImageNodes(node.children, imageNodes);
    }
  }
  return imageNodes;
}

// Listen for messages from the UI
figma.ui.onmessage = async (msg) => {
  if (msg.type === 'generate-json' || msg.type === 'generate-html') {
    const selection = figma.currentPage.selection;

    if (selection.length === 0) {
      figma.ui.postMessage({
        type: 'no-selection',
      });
      return;
    }

    try {
      if (msg.type === 'generate-json') {
        // Extract properties from all selected nodes
        const selectedElements = selection.map(node => extractNodeProperties(node));

        // Convert to formatted JSON
        const json = JSON.stringify(selectedElements, null, 2);

        // Send JSON back to UI
        figma.ui.postMessage({
          type: 'json-result',
          json: json,
          count: selection.length,
        });
      } else if (msg.type === 'generate-html') {
        // Clear previous image map
        imageUrlMap.clear();
        
        // Collect all image nodes
        const imageNodes = collectImageNodes(selection);
        const nodeIds = Array.from(imageNodes).map(n => n.id);

        // If API token is provided, use Figma REST API for hosted URLs
        if (msg.apiToken && nodeIds.length > 0) {
          // Try to get file key from multiple sources
          let fileKey = msg.fileKey || figma.fileKey;
          
          // If user pasted full URL, extract the file key
          if (fileKey && (fileKey.includes('figma.com') || fileKey.includes('/'))) {
            // Extract file key from URL patterns:
            // https://www.figma.com/file/FILE_KEY/...
            // https://www.figma.com/design/FILE_KEY/...
            const match = fileKey.match(/(?:file|design)\/([a-zA-Z0-9]+)/);
            if (match && match[1]) {
              fileKey = match[1];
              console.log('Extracted file key from URL:', fileKey);
            }
          }
          
          console.log('File key from message:', msg.fileKey);
          console.log('File key from figma.fileKey:', figma.fileKey);
          console.log('Final file key:', fileKey);
          
          if (!fileKey) {
            figma.ui.postMessage({
              type: 'error',
              error: 'File key is required when using API token. Please enter the file key from your Figma URL (figma.com/file/FILE_KEY/...).'
            });
            return;
          }

          figma.ui.postMessage({
            type: 'fetching-images',
            count: nodeIds.length
          });

          try {
            const apiUrl = `https://api.figma.com/v1/images/${fileKey}?ids=${nodeIds.join(',')}&format=png&scale=2`;
            console.log('Fetching images from:', apiUrl);
            
            const response = await fetch(apiUrl, {
              headers: {
                'X-Figma-Token': msg.apiToken
              }
            });

            console.log('API Response status:', response.status);

            if (response.ok) {
              const data = await response.json();
              console.log('API Response data:', data);
              
              if (data.images) {
                Object.keys(data.images).forEach(nodeId => {
                  imageUrlMap.set(nodeId, data.images[nodeId]);
                });
              }
              
              if (data.err) {
                figma.ui.postMessage({
                  type: 'error',
                  error: `API returned error: ${JSON.stringify(data.err)}`
                });
                return;
              }
            } else {
              const errorText = await response.text();
              console.error('API Error:', errorText);
              figma.ui.postMessage({
                type: 'error',
                error: `API Error ${response.status}: ${errorText}. File Key: ${fileKey}`
              });
              return;
            }
          } catch (fetchError) {
            console.error('Fetch error:', fetchError);
            figma.ui.postMessage({
              type: 'error',
              error: `Failed to fetch from Figma API: ${fetchError}`
            });
            return;
          }
        } else if (imageNodes.length > 0) {
          // No API token - export and embed images as base64
          figma.ui.postMessage({
            type: 'fetching-images',
            count: imageNodes.length
          });

          for (const node of imageNodes) {
            try {
              const imageBytes = await node.exportAsync({
                format: 'PNG',
                constraint: { type: 'SCALE', value: 2 }
              });
              
              const base64 = figma.base64Encode(imageBytes);
              const dataUrl = `data:image/png;base64,${base64}`;
              
              imageUrlMap.set(node.id, dataUrl);
            } catch (exportError) {
              console.error(`Failed to export node ${node.id}:`, exportError);
              imageUrlMap.set(node.id, 'placeholder.jpg');
            }
          }
        }
        
        // Generate HTML from selected nodes
        const html = generateHtmlDocument(selection);

        // Send HTML back to UI with image information
        figma.ui.postMessage({
          type: 'html-result',
          html: html,
          count: selection.length,
          imageInfo: {
            fileKey: figma.fileKey || 'unsaved',
            nodeIds: nodeIds,
            hasImages: imageNodes.length > 0,
            isEmbedded: !msg.apiToken
          }
        });
      }
    } catch (error) {
      figma.ui.postMessage({
        type: 'error',
        error: String(error),
      });
    }
  }
};
