---
version: "1.0"
name: Industrial Signal Control
description: High-density technical command center for multi-account Telegram backup and rule-based automation.
colors:
  primary: "#10B981"
  primary-hover: "#059669"
  secondary: "#F59E0B"
  neutral: "#09090B"
  surface: "#121215"
  surface-elevated: "#18181C"
  border: "#27272A"
  on-surface: "#F4F4F5"
  on-surface-muted: "#A1A1AA"
  error: "#EF4444"
typography:
  headline-lg:
    fontFamily: Space Grotesk
    fontSize: 28px
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Space Grotesk
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.25
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
  label-mono:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.4
rounded:
  none: 0px
  sm: 2px
  md: 4px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#052E16"
    rounded: "{rounded.sm}"
    padding: 10px
  card-panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.sm}"
    padding: 20px
---

# Industrial Signal Control

## Overview
A mission-critical command center for managing multiple Telegram accounts, automated file backup streams, group folder hierarchies, and real-time fallback rules. Built with crisp 2px technical edges, high-contrast zinc surfaces, and emerald/amber signal indicators (strictly zero purple/violet).

## Colors
- **Primary (`#10B981`):** Signal Emerald for active workers, connected accounts, and primary CTAs.
- **Secondary (`#F59E0B`):** Caution Amber for auto-learned group restrictions and fallback triggers.
- **Neutral (`#09090B`) & Surface (`#121215`):** Deep carbon foundation with crisp `1px solid #27272A` structural dividers.
- **Error (`#EF4444`):** Alert Red for disconnected sessions or failed transfers.

## Typography
- **Headlines (`Space Grotesk`):** Geometric, authoritative headings for control panels and metrics.
- **Body (`Plus Jakarta Sans`):** Clean, legible Vietnamese and English UI copy.
- **Monospace (`JetBrains Mono`):** Used for Chat IDs, Topic IDs, SHA-256 hashes, file extensions, and live logs.

## Layout
- Left command rail (`260px` fixed on desktop) + full-bleed operational workspace with structured data tables and interactive drawers/modals.

## Elevation & Depth
- Tonal layering (`#09090B` -> `#121215` -> `#18181C`) with sharp `1px` borders rather than blurry glassmorphism.

## Shapes
- Crisp `2px` (`rounded-sm`) technical geometry across buttons, inputs, badges, and panels.

## Components
- **Rule Matrix Toggles:** Instant single-click restriction pills (`No Link`, `No Sticker`, `No Forward`, `No Media`, `No @Bot`) with auto-learned badges.
- **Fallback Simulator Drawer:** Live preview showing how a message transforms when targeting a restricted group.

## Do's and Don'ts
- Do use monospace typography for all Telegram IDs (`-100...`), phone numbers, and SHA-256 hashes.
- Don't use purple, indigo, or violet hues anywhere in the interface.
- Do provide immediate visual feedback on every action (OTP login, dialog scan, backup sync, fallback simulation).

