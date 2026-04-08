# Design System Specification: The Architectural Precision System

## 1. Overview & Creative North Star: "The Digital Atrium"
This design system is built upon the concept of **The Digital Atrium**. In architectural terms, an atrium provides a sense of light, air, and structural integrity. For a PC application, this translates to a workspace that feels expansive yet grounded.

We are moving away from "boxed-in" software. Instead of rigid grids and heavy borders, we utilize **intentional asymmetry** and **tonal depth**. The interface should feel like a high-end physical object—think of a precision-machined aluminum chassis or a stack of fine-milled paper. We break the "template" look by using exaggerated typographic scales (Manrope for displays) contrasted against the hyper-functional Inter for utility, creating an editorial feel that suggests authority and calm.

---

## 2. Color Theory & Surface Strategy

The color palette is anchored by the sophisticated `primary` (#00647c) and a range of "Living Grays." 

### The "No-Line" Rule
To achieve a premium, airy aesthetic, **1px solid borders are strictly prohibited for sectioning.** Boundaries between functional areas must be defined exclusively through:
1.  **Background Color Shifts:** Using `surface` transitions (e.g., a `surface-container-low` sidebar against a `surface` main stage).
2.  **Negative Space:** Utilizing the Spacing Scale (specifically `8` to `16`) to create mental boundaries.

### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers. Use the following tiers to define importance:
*   **Base:** `surface` (#f8f9fa) — The foundation of the application.
*   **Recessed:** `surface-container` (#edeeef) — For secondary utility areas like sidebars or footers.
*   **Elevated:** `surface-container-lowest` (#ffffff) — Reserved for primary content cards or the main active workspace to make it "pop" against the light gray base.

### The Glass & Signature Textures
*   **The Signature Gradient:** For Hero CTAs and primary action states, do not use flat colors. Use a subtle linear gradient: `primary` (#00647c) to `primary_container` (#007f9d) at a 135° angle. This adds "visual soul."
*   **Glassmorphism:** Floating menus (overlays, dropdowns) should use `surface_container_lowest` at 85% opacity with a `backdrop-filter: blur(12px)`.

---

## 3. Typography: Editorial Utility

The system pairs **Manrope** (Headlines) for industrial elegance with **Inter** (Body) for high-precision readability.

| Level | Token | Font | Size | Character |
| :--- | :--- | :--- | :--- | :--- |
| **Display** | `display-lg` | Manrope | 3.5rem | Bold, tight tracking (-0.02em) |
| **Headline** | `headline-md` | Manrope | 1.75rem | Medium, for section titles |
| **Title** | `title-lg` | Inter | 1.375rem | Semibold, for card headers |
| **Body** | `body-md` | Inter | 0.875rem | Regular, optimized for PC reading |
| **Label** | `label-sm` | Inter | 0.6875rem | Uppercase, +0.05em tracking for metadata |

**Editorial Note:** Use `display-lg` sparingly to anchor a page. The contrast between a massive headline and a small, precise `label-sm` creates a "high-end boutique" feel.

---

## 4. Elevation & Depth: Tonal Layering

Traditional "drop shadows" are often a sign of lazy design. We use **Ambient Depth**.

*   **The Layering Principle:** Rather than adding a shadow to a card, place a `surface_container_lowest` (#ffffff) card on a `surface_container` (#edeeef) background. The 1.5% brightness difference is enough for the human eye to perceive depth without visual clutter.
*   **Ambient Shadows:** If an element must float (e.g., a Modal), use an ultra-diffused shadow:
    *   `box-shadow: 0 12px 32px -4px rgba(25, 28, 29, 0.06);`
    *   The color is a tinted version of `on_surface` to mimic natural light.
*   **The Ghost Border Fallback:** If accessibility requirements demand a border, use `outline_variant` (#bdc8ce) at **20% opacity**. It should be felt, not seen.

---

## 5. Components

### Buttons
*   **Primary:** Uses the Signature Gradient. Corner radius is strictly `DEFAULT` (0.5rem).
*   **Secondary:** `surface_container_high` with `on_surface` text. No border.
*   **Tertiary:** Transparent background, `primary` text. Use for low-emphasis actions.

### Cards & Lists
*   **Rule:** Forbid divider lines.
*   **Execution:** Use `surface_container_low` for the list background and `surface_container_lowest` for the individual list item on hover. Separate items using `spacing.2` (0.5rem).

### Input Fields
*   **State:** Unfocused inputs use `surface_container_high`. 
*   **Focus State:** Shift to `surface_container_lowest` with a 2px `surface_tint` (006780) bottom-only accent. This maintains the "industrial" feel of the system.

### Interactive "Breadcrumbs" (The Nav-Pill)
Instead of standard tabs, use "Nav-Pills" with `rounded-full` (9999px). An active state is indicated by a `secondary_container` background, creating a soft "pill" that feels approachable and modern.

---

## 6. Do’s and Don’ts

### Do
*   **Do** use asymmetrical padding. Give more space to the top of a container than the bottom to create an "upward" energy.
*   **Do** use `primary_fixed_dim` for subtle accent backgrounds in data visualization.
*   **Do** rely on `body-sm` for "micro-copy"—professional software is built on density, but keep it legible.

### Don't
*   **Don't** use pure black (#000000) for text. Use `on_surface` (#191c1d) to maintain the airy, light feel.
*   **Don't** use standard "Success Green." Lean into the `tertiary` (#894e00) or `primary` tones for status unless it is a critical error.
*   **Don't** use the `xl` (1.5rem) corner radius for small components; keep those to `DEFAULT` (0.5rem) to maintain the "Precise/Industrial" mood. `xl` is reserved for large hero containers only.