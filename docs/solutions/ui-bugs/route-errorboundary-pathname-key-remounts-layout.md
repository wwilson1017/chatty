---
title: Pathname-keyed route ErrorBoundary remounts layout routes, resetting their state
date: 2026-06-10
category: ui-bugs
module: frontend/src/shared/AppShell.tsx
tags: [react, react-router, error-boundary, layout-routes, remount, crm, demo-dialog]
problem_type: ui_bug
---

## Problem

A route-level `ErrorBoundary` keyed by `location.pathname` (so navigating away resets a crashed route) silently remounts React Router *layout routes* on every child-route navigation, wiping their component state.

## Symptoms

- In CRM demo mode, dismissing the `DemoDialog` modal worked — until the user clicked any other CRM tab, at which point the full modal popped back up. Every tab switch re-showed it.
- `/api/crm/demo-status` was refetched on every CRM tab navigation (mount effect re-running).
- No errors anywhere; the app "worked" — the regression was purely behavioral and only visible in the first-run demo flow.

## What Didn't Work

- **Three review passes missed it.** A 4-persona review, a 3-turn Codex review, and a Gemini review all examined the diff that introduced `key={location.pathname}`; none connected the key to layout-route state. It was caught only by a final-stage review explicitly prompted to check "does the pathname-keyed boundary interact correctly with every route (CRM nested routes…)".
- The risk *was* listed in the implementation plan ("CrmLayout remounts on CRM tab switches… escape hatch if it bites") but rated acceptable without tracing what state CrmLayout actually holds.

## Solution

Collapse nested-route groups to a single boundary key (`frontend/src/shared/AppShell.tsx`):

```tsx
<ErrorBoundary
  key={location.pathname.startsWith('/crm') ? '/crm' : location.pathname}
  fallback={(error, reset) => <RouteErrorFallback error={error} reset={reset} />}
>
  <Outlet context={{ branding, setBranding }} />
</ErrorBoundary>
```

`CrmLayout` now stays mounted across `/crm`, `/crm/contacts`, `/crm/pipeline`, `/crm/tasks`; only its `<Outlet>` reconciles, as React Router intends for layout routes.

## Why This Works

With declarative `<Routes>`, navigating between children of a layout route normally keeps the layout element instance stable. But a `key` on **any ancestor** that changes with the pathname forces React to unmount and remount the entire subtree — including the layout — discarding `useState` (`dialogDismissed`, `demoMode`) and re-running mount effects.

Keying by route *group* preserves the original intent (a crashed leaf page resets when you navigate to a different section) while keeping layout instances stable within their group.

Accepted trade-off: a crash inside CRM no longer auto-resets by switching CRM tabs — those tabs render inside the crashed subtree anyway, so they're unreachable; recovery is via the fallback's "Back to Dashboard"/"Reload" buttons (the fallback also receives an explicit `reset()` for the crashed-at-same-pathname case).

## Prevention

- When adding a pathname-derived `key` to anything that wraps an `<Outlet>`, enumerate the layout routes beneath it and check what state/effects they own before shipping.
- Per-route param keys are fine when remounting is *desired* (e.g. `/agent/:id` — switching agents should reset the page); the hazard is specifically layouts whose children change the pathname.
- The same class of bug applies to keying by `location.key` or full `location.search` — anything that changes more often than the subtree's intended lifetime.
