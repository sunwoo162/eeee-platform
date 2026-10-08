# EEEE Core and Optional Plugin Architecture

## Goal

Make EEEE a general-purpose personal assistant whose basic conversation and
decision-making work without optional integrations, while allowing installed
plugins to extend specific tasks such as project development, calendars,
documents, and GitHub.

## Product boundary

EEEE is the product the user talks to. A request always enters EEEE first.
EEEE may answer directly, perform a local action, or select an enabled plugin
when that plugin materially improves execution quality or accuracy.

ISEOL is not the identity of EEEE. It is the built-in project-development
plugin that EEEE invokes for software-project requests. ClaimLatch is the
built-in trust and release-verification plugin used around assistant claims,
plugin outputs, evidence, QA, and memory promotion.

Notion, Google Calendar, GitHub, Slack, and similar existing services are not
installed by default. They are optional plugins/connectors that can be
installed, connected, paused, resumed, or removed by the user.

## Runtime rules

1. EEEE receives every user message through the canonical assistant route.
2. The assistant first classifies the request as conversation, local action,
   or plugin-capable work.
3. Direct conversation and local capabilities remain available when no plugin
   is installed.
4. Only registered and enabled plugins may be selected automatically.
5. If a request needs an unavailable plugin, EEEE explains the missing
   capability and offers installation/connection; it must not silently fake a
   successful external action.
6. A paused or disconnected plugin is excluded from routing until resumed.
7. Plugin invocation, result, evidence, and user-visible claim pass through
   the existing execution ledger and ClaimLatch trust boundary.
8. ISEOL project work must still create a plan, split work among specialist
   agents, run independent QA, and publish only after ClaimLatch/release gates.
9. Memory promotion records the user preference or verified outcome, not an
   unverified plugin claim.

## Installation model

Each plugin is represented by the existing local manifest/host model:

- `id`: stable plugin identifier
- `name` and `description`: user-facing metadata
- `capabilities`: intents/actions it can handle
- `permissions`: data and external side effects it may access
- `installState`: `builtin`, `installed`, or `available`
- `connectionState`: `disconnected`, `connected`, `paused`, or `error`

Built-in plugins are available in a fresh local installation. Optional
plugins remain absent until the user installs and explicitly connects them.
No hosted plugin registry or account is required for the local core; discovery
may use a future package/catalog adapter.

## UI behavior

The desktop pet remains an EEEE surface, not a project dashboard. The default
view shows only the character and one assistant speech bubble. A command
surface opens on interaction. Project status, plugin state, and detailed
execution maps are secondary views opened only when relevant.

## Error and trust behavior

- No matching direct capability: EEEE asks a clarification question.
- Matching optional plugin is missing: EEEE reports `plugin_required` and
  names the install/connect action.
- Plugin is paused or permission is denied: EEEE reports the blocked action
  and offers a safe alternative.
- ClaimLatch is unavailable or returns a non-PASS result: the assistant may
  describe the limitation, but cannot present the affected result as verified
  or release it as complete.

## Verification requirements

- Route a normal conversation without any optional plugin.
- Route a project request to ISEOL and preserve its existing QA/release flow.
- Exclude an optional plugin when it is not installed, paused, or disconnected.
- Return a structured missing-plugin response without performing the action.
- Re-enable a plugin and verify it becomes routable.
- Confirm every plugin result retains execution identity and ClaimLatch
  verification metadata.
- Confirm the default desktop view does not expose project-only controls.
