# MCP Tool List

Manual tool list for the MCP server, grouped by capability.

## Layout / Structure

- `beefree_add_section` — Add a new section (row with columns). Inputs: `columns` (required, weights must sum to 12), optional `position`, `rowBackgroundColor`, `contentArea*` styles, `verticalAlign`, `columnsSpacing`, `columnsBorderRadius`, `hideOnMobile`, `hideOnDesktop`.
- `beefree_delete_element` — Delete any element. Inputs: `elementId` (required).
- `beefree_update_section_style` — Update section styles. Inputs: `sectionId` (required), optional row/content area colors, borders, padding, alignment, spacing, `hideOnMobile`, `hideOnDesktop`.
- `beefree_update_column_style` — Update column styles. Inputs: `columnId` (required), optional background, padding, borders.

## Editor Sync

- `beefree_get_selected` — Get current selection. Inputs: optional `includeDetails`.
- `beefree_get_content_hierarchy` — Get section/column/block tree. Inputs: optional `includeIds`, `includePositions`, `includeBlockTypes`.
- `beefree_get_element_details` — Get element details. Inputs: `elementId` (required).

## Template Catalog

- `beefree_retrieve_template_facets` — Get categories/tags/collections. Inputs: optional `includeCounts`.
- `beefree_list_templates` — List templates filtered by catalog facets. Inputs: `category` or `tag` or `collection` (at least one required), optional `page`.
- `beefree_clone_template` — Clone a catalog template. Inputs: `sourceTemplateId` (required), optional `updateBranding`, `primaryColor`, `secondaryColor`, `fontFamily`, `logoUrl`, `preserveContent`.

## Checker

- `beefree_check_template` — Validate whole template. Inputs: any combination of boolean flags (e.g., `includeMissingAltText`, `includeMissingEmailDetail`, `includeInsufficientColorContrast`, `includeUnreachableWebLink`, `includeMissingHeadings`, `includeOverageHeadings`, `includeMissingMainLanguage`).
- `beefree_check_section` — Validate one section. Inputs: `sectionId` (required) plus boolean flags (e.g., `includeMissingAltText`, `includeMissingImageLink`, `includeMissingCopyLink`, `includeInsufficientColorContrast`, `includeUnreachableWebLink`).

## Preset Sections

- `beefree_get_preset_sections_categories` — List preset section categories. Inputs: optional `dummyParam`.
- `beefree_get_preset_sections_per_category` — List preset sections by category. Inputs: `category` (required).
- `beefree_add_preset_section` — Insert preset section. Inputs: `category`, `sectionId`, `sectionIdField` (all required), optional `position`.

## Content Blocks — Text

- `beefree_add_paragraph` — Add paragraph block. Inputs: `section`, `column`, `index` (required), optional `html`, typography, spacing, padding, mobile variants, `hideOnMobile`, `hideOnDesktop`, `mergeTagPassed`.
- `beefree_update_paragraph` — Update paragraph block. Inputs: `elementId` (required), optional same fields as add.
- `beefree_add_title` — Add heading block. Inputs: `section`, `column`, `index` (required), optional `text`, `headingLevel` (`h1`–`h3`), typography, padding/mobile, `hideOnMobile`, `hideOnDesktop`, `mergeTagPassed`.
- `beefree_update_title` — Update heading block. Inputs: `elementId` (required), optional same fields as add.
- `beefree_add_list` — Add list block. Inputs: `section`, `column`, `index`, `listType` (`ul`/`ol`), `items` (required); optional list styling, typography, padding/mobile, `hideOnMobile`, `hideOnDesktop`, `mergeTagPassed`.
- `beefree_update_list` — Update list block. Inputs: `elementId` (required), optional same fields as add.
- `beefree_add_menu` — Add menu block. Inputs: `section`, `column`, `index`, `items` (required); optional layout, separator, spacing, hamburger options, typography, padding/mobile, `hideOnMobile`, `hideOnDesktop`.
- `beefree_update_menu` — Update menu block. Inputs: `elementId` (required), optional same fields as add.

## Content Blocks — Media

- `beefree_add_image` — Add image block. Inputs: `section`, `column`, `index`, `src` (required); optional `alt`, `href`, `width`, `align`, `borderRadius`, `padding`, `hideOnMobile`, `hideOnDesktop`.
- `beefree_update_image` — Update image block. Inputs: `elementId` (required); optional same fields as add.
- `beefree_search_stock_images` — Search stock images (Pexels). Inputs: `query`, `desired_height`, `desired_width` (required), optional `orientation`, `color`.
- `beefree_add_social` — Add social icons block. Inputs: `section`, `column`, `index`, `socialIcons` (required); optional `iconStyle`, `iconSize`, `iconSpacing`, `align`, padding/mobile, `hideOnMobile`, `hideOnDesktop`.
- `beefree_update_social` — Update social icons block. Inputs: `elementId` (required); optional same fields as add.
- `beefree_add_icon` — Add custom icon block. Inputs: `section`, `column`, `index`, `icons` (required; each includes at least `src`); optional typography, spacing, padding/mobile, `hideOnMobile`, `hideOnDesktop`.
- `beefree_update_icon` — Update custom icon block. Inputs: `elementId` (required); optional same fields as add.

## Content Blocks — Buttons

- `beefree_add_button` — Add button block. Inputs: `section`, `column`, `index`, `text` (required); optional `href`, typography, colors, borders, padding/mobile, widths, `hideOnMobile`, `hideOnDesktop`, `mergeTagPassed`.
- `beefree_update_button` — Update button block. Inputs: `elementId` (required); optional same fields as add.

## Content Blocks — Separators

- `beefree_add_spacer` — Add spacer block. Inputs: `section`, `column`, `index` (required); optional `height`, `hideOnMobile`.
- `beefree_update_spacer` — Update spacer block. Inputs: `elementId` (required); optional `height`, `hideOnMobile`.
- `beefree_add_divider` — Add divider block. Inputs: `section`, `column`, `index` (required); optional `line`, `width`, `align`, `padding`, `hideOnMobile`, `hideOnDesktop`.
- `beefree_update_divider` — Update divider block. Inputs: `elementId` (required); optional `line`, `width`, `align`, `padding`, `hideOnMobile`, `hideOnDesktop`.

## Content Blocks — Tables

- `beefree_add_table` — Add table block. Inputs: `section`, `column`, `index` (required); optional `headers`, `rows`, typography, colors, borders, padding, `hideOnMobile`, `hideOnDesktop`, `mergeTagPassed`.
- `beefree_update_table` — Update table block. Inputs: `elementId` (required); optional same fields as add.

## Email Settings

- `beefree_set_email_metadata` — Set subject/preheader. Inputs: optional `subject`, `preheader`.
- `beefree_set_email_default_styles` — Set default styles. Inputs: optional `contentAreaWidth`, `contentAreaAlignment`, `backgroundColor`, `contentAreaBackgroundColor`, `fontFamily`, `linkColor`.

## Notes / Gating

- Tool availability can be filtered at runtime by `client_id`.
- Preset section tools are gated by an allowlist (`savedRowsIDs`).
