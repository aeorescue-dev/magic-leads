# Source manifest

Attach these files from the parent project together with this folder:

```text
src/App.tsx
src/i18n.ts
src/index.css
```

The current landing does not require the hero JPG asset. If the official implementation decides to use the previous image, attach:

```text
public/magic-leads-hero.jpg
```

These files are a React/Vite reference. OpenCode must convert them to Next.js 14 App Router instead of replacing the official app entry point with Vite code.

## Current reference features

- Light-first layout matching the dashboard light mode
- Dark product preview and final CTA sections matching the dashboard dark mode
- PT, EN and ES flag selector with full copy switching
- Real-time-style aggregate fields with relative update wording
- Cities and service categories based on the current product scope
- Interactive sample panel, reserve state, calculator, templates and FAQ
- Responsive header, mobile menu, footer and conversion modal