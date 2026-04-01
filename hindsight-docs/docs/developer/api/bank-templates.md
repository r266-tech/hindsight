---
sidebar_position: 9
---

# Bank Templates

Declarative JSON manifests for creating pre-configured memory banks with a single API call.

## Overview

A bank template is a JSON manifest that describes a bank's full setup: configuration overrides, mental models, and (in the future) other resources. Instead of making multiple API calls to configure a bank, you submit one manifest and the API provisions everything.

Templates are useful for:
- **Replication** — stamp out identically-configured banks for multiple users or agents
- **Onboarding** — new users start with a known-good configuration instead of configuring from scratch
- **Sharing** — distribute recommended setups as portable JSON files
- **Framework integrations** — ship a recommended template alongside your integration

Browse the [Template Gallery](/templates) for ready-to-use templates.

## Manifest Schema

```json
{
  "version": "1",
  "description": "Human-readable description (optional)",
  "bank": {
    "reflect_mission": "...",
    "retain_mission": "...",
    "retain_extraction_mode": "concise | verbose | custom | chunks",
    "retain_custom_instructions": "...",
    "retain_chunk_size": 2048,
    "disposition_skepticism": 3,
    "disposition_literalism": 3,
    "disposition_empathy": 3,
    "enable_observations": true,
    "observations_mission": "...",
    "entity_labels": ["PERSON", "ORGANIZATION"],
    "entities_allow_free_form": true
  },
  "mental_models": [
    {
      "id": "unique-lowercase-id",
      "name": "Human-Readable Name",
      "source_query": "The query that generates this mental model's content",
      "tags": ["optional", "tags"],
      "max_tokens": 2048,
      "trigger": {
        "refresh_after_consolidation": false,
        "fact_types": ["world", "experience", "observation"],
        "exclude_mental_models": false,
        "exclude_mental_model_ids": []
      }
    }
  ],
  "directives": [
    {
      "name": "directive-name",
      "content": "The directive instruction text",
      "priority": 0,
      "is_active": true,
      "tags": ["optional", "tags"]
    }
  ]
}
```

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `version` | Yes | Schema version. Currently `"1"`. |
| `description` | No | Human-readable description of the template. |
| `bank` | No | Bank configuration overrides. Omit to leave config unchanged. |
| `mental_models` | No | Mental models to create or update. Omit to leave unchanged. |
| `directives` | No | Directives to create or update. Omit to leave unchanged. |

All of `bank`, `mental_models`, and `directives` are optional. Omit any section to leave that part of the bank unchanged.

### Bank Config Fields

All fields in `bank` are optional. Only the fields you include will be set as per-bank overrides — everything else inherits from the server/tenant defaults.

| Field | Type | Description |
|-------|------|-------------|
| `reflect_mission` | string | Mission/context for reflect operations |
| `retain_mission` | string | Steers what gets extracted during retain |
| `retain_extraction_mode` | string | `concise`, `verbose`, `custom`, or `chunks` |
| `retain_custom_instructions` | string | Custom extraction prompt (requires `mode=custom`) |
| `retain_chunk_size` | integer | Max token size per content chunk |
| `disposition_skepticism` | integer (1-5) | How skeptical the disposition is |
| `disposition_literalism` | integer (1-5) | How literal the disposition is |
| `disposition_empathy` | integer (1-5) | How empathetic the disposition is |
| `enable_observations` | boolean | Toggle observation consolidation |
| `observations_mission` | string | Controls what gets synthesised into observations |
| `entity_labels` | string[] | Controlled vocabulary for entity labels |
| `entities_allow_free_form` | boolean | Allow entities outside the label vocabulary |

### Mental Model Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique ID (lowercase alphanumeric with hyphens). Used to match on re-import. |
| `name` | Yes | Human-readable name |
| `source_query` | Yes | The query that generates this model's content via reflect |
| `tags` | No | Tags for scoped visibility. Default: `[]` |
| `max_tokens` | No | Max tokens for generated content (256-8192). Default: `2048` |
| `trigger` | No | Trigger settings for auto-refresh |

### Directive Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Directive name. Used as the match key on re-import. |
| `content` | Yes | The directive instruction text. |
| `priority` | No | Priority value (higher = more important). Default: `0` |
| `is_active` | No | Whether the directive is active. Default: `true` |
| `tags` | No | Tags for categorization. Default: `[]` |

## Import

Import a manifest into a bank. If the bank doesn't exist, it's created automatically.

```bash
curl -X POST http://localhost:8888/v1/default/banks/my-bank/import \
  -H "Content-Type: application/json" \
  -d @template.json
```

### Behavior

- **Config**: all `bank` fields are applied as per-bank config overrides
- **Mental models**: matched by `id` — existing models are updated, new ones are created
- **Directives**: matched by `name` — existing directives are updated, new ones are created
- **Async**: mental model content is generated asynchronously. The response includes `operation_ids` to track progress.

### Response

```json
{
  "bank_id": "my-bank",
  "config_applied": true,
  "mental_models_created": ["sentiment-overview"],
  "mental_models_updated": ["unresolved-issues"],
  "directives_created": ["always-acknowledge-frustration"],
  "directives_updated": ["no-internal-ids"],
  "operation_ids": ["op-1", "op-2"],
  "dry_run": false
}
```

### Dry Run

Validate a manifest without applying changes:

```bash
curl -X POST http://localhost:8888/v1/default/banks/my-bank/import?dry_run=true \
  -H "Content-Type: application/json" \
  -d @template.json
```

Returns what *would* happen (which config would be applied, which mental models would be created) without making any changes. Returns HTTP 400 with a detailed error message if the manifest is invalid.

## Export

Export a bank's current config overrides and mental models as a manifest:

```bash
curl http://localhost:8888/v1/default/banks/my-bank/export
```

The exported manifest only includes config fields that were explicitly set as per-bank overrides — not the fully resolved config (which includes server/tenant defaults). This means the exported manifest is portable: importing it into a new bank only overrides the fields that were intentionally customized.

### Round-trip

Export from one bank and import into another to replicate the setup:

```bash
# Export
curl http://localhost:8888/v1/default/banks/source-bank/export > template.json

# Import into a new bank
curl -X POST http://localhost:8888/v1/default/banks/new-bank/import \
  -H "Content-Type: application/json" \
  -d @template.json
```

## Control Plane

The control plane bank creation dialog includes an optional "Template" textarea. Paste a manifest JSON to pre-configure the bank on creation.

## Versioning

The `version` field enables forward-compatible schema evolution. The current version is `"1"`.

When future versions are released:
- Older manifests are automatically upgraded to the current schema on import
- Export always produces the latest version
- The API rejects manifests with a version newer than what the server supports (with a clear error message suggesting an upgrade)

This means old templates keep working indefinitely — no need to manually update them.
