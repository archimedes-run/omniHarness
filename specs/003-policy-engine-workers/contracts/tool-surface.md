# Contract: Tool Surface Allow/Deny

Controls what the agent can call **at all**. This is an existence question, not a tier question (FR-012, FR-013).

## Why this is separate from the policy config

A denied tool has no tier, because it is not present. Expressing "absent" as a tier would make it the weakest kind of guarantee — one enforced by a check that runs — where FR-012 asks for the strongest: a capability that cannot be reached.

The email send capability is the case that motivates it. Classifying `send` as Tier 3 means a bug in the confirmation path can send mail. Removing it from the surface means no bug in this feature can, because there is nothing to call. Drafts are their own gate: nothing leaves until the user presses send themselves.

## Shape

Per server, in the MCP server configuration:

```json
{
  "mcpServers": {
    "gmail": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["..."],
      "tools": {
        "deny": ["send_email", "send_draft"]
      }
    }
  }
}
```

`allow` and `deny` name tools **unprefixed** — as the server exposes them, not as `<server>_<tool>` after prefixing. The user configures a server; they should not have to know the assembly convention.

When both are present, `allow` is the whitelist and `deny` subtracts from it.

## The two application points

Two independent paths assemble tools, and **both must apply the list**:

| Path | Where it is applied |
|---|---|
| MCP (`local:<server>`) | between `get_tools()` and `extend()`, per server |
| Composio connector (`connector:<SLUG>`) | where connector tools are loaded live per user |

Gmail and Google Calendar exist as connector toolkits **today**. A deny applied only at the MCP layer leaves `connector:GMAIL` and its send tool fully exposed.

## The acceptance test asserts on the final list

Not on either path, and not on the presence of a configuration entry:

> the denied tool does not appear among the tools the agent can call

This is what SC-004 means by "verifiable by inspection of what the agent can call, not by a policy rule". It also means a **third** assembly path added later fails this gate rather than slipping past it — the boundary is the outcome, not the known routes.

## Rejected: execution interceptors

The MCP client already accepts `tool_interceptors`, and they are the obvious hook. They wrap execution, which yields *guarded*. FR-012 requires *absent*. Recorded so this is not rediscovered later as a simplification.
