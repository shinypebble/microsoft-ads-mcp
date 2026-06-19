# microsoft-ads-mcp

[![CI](https://github.com/shinypebble/microsoft-ads-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/shinypebble/microsoft-ads-mcp/actions/workflows/ci.yml)

An MCP server for the **Microsoft Advertising (Bing Ads) REST API**, built for agent-led
campaign management and reporting. It exposes a focused set of *useful-work* tools — walk the
campaign tree, create **and edit in place** (rename, repoint Final URLs, tracking templates,
status, bids), manage negative keywords, ad extensions, conversion goals/UET tags, and ZIP
location targeting, run the Bulk API, and pull performance reports that are actually downloaded
and parsed for you — rather than a 1:1 mirror of the API surface.

Built with [FastMCP](https://gofastmcp.com) and the official Microsoft
[`msads`](https://pypi.org/project/msads/) REST SDK (which ships OpenAPI-generated **Pydantic
v2** models). Managed with `uv`, linted/formatted with `ruff`, type-checked with `ty`.

## Why REST / `msads` (not the legacy SOAP `bingads` SDK)

Microsoft is retiring the SOAP API: **new features are REST-only from Oct 1, 2026**, and SOAP
is **fully deprecated on Jan 31, 2027** ([migration guide](https://learn.microsoft.com/en-us/advertising/guides/migrate-to-rest?view=bingads-13)).
The REST SDK `msads` gives typed Pydantic models, structured HTTP exceptions, and the same
OAuth/`ServiceClient` entry points — so this server is built on it directly.

### SDK quirks worth knowing

- **`msads` is synchronous** (requests/urllib3). Tools here are therefore plain sync
  functions; FastMCP runs them in a worker thread, so the event loop is never blocked. We do
  not wrap the SDK in async.
- **`msads` does not declare its `python-dateutil` dependency**, even though
  `openapi_client` imports it. We pin `python-dateutil` explicitly in `pyproject.toml`.
- The package installs as the `bingads.*` (auth + `ServiceClient`) and `openapi_client.*`
  (models + exceptions) import namespaces — there is no top-level `msads` module.

## REST API reference & endpoints

Pydantic models shipped inside `msads` are
code-generated from Microsoft's internal spec; the public surface is the per-operation
[Campaign Management reference](https://learn.microsoft.com/en-us/advertising/campaign-management-service/campaign-management-service-reference?view=bingads-13)
on Microsoft Learn (the [Python SOAP→REST migration guide](https://learn.microsoft.com/en-us/advertising/guides/python-sdk-migration-soap-to-rest?view=bingads-13)
is the most useful map of REST request/response shapes).

The REST service base URLs `ServiceClient` targets — set automatically from
`MICROSOFT_ADS_ENVIRONMENT` — are:

| Service | Production | Sandbox |
|---|---|---|
| Campaign Management | `https://campaign.api.bingads.microsoft.com` | `https://campaign.api.sandbox.bingads.microsoft.com` |
| Reporting | `https://reporting.api.bingads.microsoft.com` | `https://reporting.api.sandbox.bingads.microsoft.com` |
| Bulk | `https://bulk.api.bingads.microsoft.com` | `https://bulk.api.sandbox.bingads.microsoft.com` |
| Ad Insight | `https://adinsight.api.bingads.microsoft.com` | `https://adinsight.api.sandbox.bingads.microsoft.com` |
| Customer Mgmt / Billing | `https://clientcenter.api.bingads.microsoft.com` | `https://clientcenter.api.sandbox.bingads.microsoft.com` |

## Quickstart

```bash
uv sync                              # create .venv and install
cp .env.example .env                 # then set the credentials below
uv run python -m microsoft_ads_mcp   # run over stdio (default)
```

## Configuration

Set via environment variables or a local `.env` (see [.env.example](.env.example)):

| Variable | Required | Notes |
|---|---|---|
| `MICROSOFT_ADS_DEVELOPER_TOKEN` | yes | From the developer portal |
| `MICROSOFT_ADS_CLIENT_ID` | yes | OAuth app (client) id — an Azure app, or a Google Cloud OAuth client when `IDENTITY_PROVIDER=google` |
| `MICROSOFT_ADS_IDENTITY_PROVIDER` | no | `microsoft` (default) or `google` for Google-federated accounts |
| `MICROSOFT_ADS_REFRESH_TOKEN` | recommended | Run non-interactively; else mint one via the auth tools |
| `MICROSOFT_ADS_CLIENT_SECRET` | no | Microsoft web/confidential apps, or the Google OAuth client secret |
| `MICROSOFT_ADS_ACCOUNT_ID` / `MICROSOFT_ADS_CUSTOMER_ID` | no | Discovered via `search_accounts` if unset |
| `MICROSOFT_ADS_ENVIRONMENT` | no | `production` (default) or `sandbox` |
| `READ_ONLY` | no | `true` registers no write tools at all (default `false`) |
| `TOOL_SEARCH` | no | `true` collapses the catalog behind BM25 `search_tools` / `call_tool` with a few tools pinned; typed schemas and the `READ_ONLY` gate are preserved (default `false`) |

Refresh tokens are persisted to `~/.config/microsoft-ads/tokens.json`, created with `0600`
permissions (owner read/write only).

## Authentication

If you have no refresh token yet, mint one once (interactive):

1. Call `get_auth_url()` → open the URL, sign in.
2. Copy the redirect URL and call `complete_auth(redirect_url)`.
3. The refresh token is saved and reused/auto-refreshed thereafter.

## MCP client configuration

```json
{
  "mcpServers": {
    "microsoft-ads": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "${CLAUDE_PROJECT_DIR:-.}", "python", "-m", "microsoft_ads_mcp"],
      "env": {
        "MICROSOFT_ADS_DEVELOPER_TOKEN": "...",
        "MICROSOFT_ADS_CLIENT_ID": "...",
        "MICROSOFT_ADS_REFRESH_TOKEN": "...",
        "READ_ONLY": "false"
      }
    }
  }
}
```

## Tools

Call `account_health` first to validate credentials and learn whether writes are enabled. It
returns a discriminated `auth_state` (`ok` / `no_token` / `token_expired` / `token_rejected` /
`dev_token_missing` / `account_inactive`) and `needs_interactive_auth`, so a client can branch
deterministically instead of pattern-matching an error string.

**Auth** — `get_auth_url`, `complete_auth` (one-time interactive sign-in; see below).

**Read** — `account_health`, `search_accounts`, `set_active_account` (switch which account
calls hit), `get_campaigns`, `get_ad_groups`, `get_keywords`, `get_ads` (includes the RSA copy:
headlines / descriptions / paths), `get_budgets`, `get_negative_keywords`, `get_ad_extensions`,
`get_conversion_goals`, `get_uet_tags`, `get_location_targets`, `get_location_intent`
(presence vs. search-interest targeting), `get_ad_schedules` (dayparting windows plus the
campaign time zone they run in), `get_device_bid_adjustments` (per-device modifiers —
Computers / Smartphones / Tablets), `resolve_postal_codes`
(ZIP → Microsoft LocationId), `bulk_download`, `get_account_url_options`. `get_campaigns` also
surfaces each campaign's `time_zone`, `start_date`, `languages`, `bid_strategy_type`, and
`ad_schedule_use_searcher_time_zone`. The hierarchy reads
(`get_campaigns`, `get_ad_groups`, `get_ads`, `get_keywords`) also surface each entity's URL
tracking — `tracking_url_template`, `final_url_suffix`, and `url_custom_parameters`. A `null`
template at a level usually means it inherits the **account-level** default, which
`get_account_url_options` returns (tracking template, Final URL suffix, and
`msclkid_auto_tagging_enabled` — the Microsoft Click ID that drives attribution). Confirm these
before activating paused campaigns rather than assuming the per-campaign blanks mean "untracked".
`get_conversion_goals` reports each goal's `exclude_from_bidding` — the inverse of the UI's
"Include in conversions" checkbox, i.e. whether the goal feeds automated bidding (ECPC / tCPA) —
plus `count_type`, `conversion_window_in_minutes`, `goal_category`, and the revenue model; confirm
a goal is included before relying on it to steer spend.

**Reporting** — `run_performance_report` (submit → poll → download → parse, returns rows),
covering campaign / keyword / search-query / geographic reports. Supports a predefined
`date_range` or a custom `start_date`/`end_date`, and scoping to a single `campaign_id` /
`ad_group_id` / `account_id`.

**Write** (only when `READ_ONLY=false`) — new campaigns / ad groups / ads are created **PAUSED**.

- *Campaigns, ad groups, ads, keywords* — `create_campaign`, `update_campaign`,
  `update_campaign_status`, `create_ad_group`, `update_ad_group`, `create_responsive_search_ad`,
  `update_responsive_search_ad`, `add_keywords`, `update_keyword`, `delete_campaign`,
  `delete_ad_group`, `delete_ad`, `delete_keyword`. Create/update at every level (campaign, ad
  group, ad, keyword) accept `tracking_url_template`, `final_url_suffix`, and
  `url_custom_parameters` (a `{key: value}` map, referenced in templates as `{_key}`).
- *Account-level URL options* — `set_account_url_options` sets the tracking template, Final URL
  suffix, and `msclkid` auto-tagging once for the whole account (every campaign inherits them) —
  the cleanest single-point lever for an account-wide tracking/rebrand change.
- *Negative keywords* — `add_negative_keywords`, `remove_negative_keywords` (campaign or ad-group
  scope).
- *Ad extensions* — `add_call_extension`, `update_call_extension`, `add_callout_extension`,
  `add_sitelink_extension`, `delete_ad_extension`. Call extensions accept
  `is_call_tracking_enabled` (US/UK) to turn on Microsoft call tracking so call-from-ad
  conversions are measured — pass it on `add_call_extension`, or flip it on an existing asset
  with `update_call_extension`. New forwarding numbers are local (toll-free is no longer
  provisioned). `get_ad_extensions` surfaces the current `is_call_tracking_enabled` flag.
- *Conversion goals / UET tags* — `update_conversion_goal` edits a goal in place: rename, set
  `status`, and (most launch-relevant) toggle `exclude_from_bidding` — the inverse of the UI's
  "Include in conversions" checkbox, the single switch for whether a goal feeds automated bidding
  (ECPC / tCPA). Also sets `count_type`, `conversion_window_in_minutes`, and the revenue model
  (`revenue_type` / `revenue_value` / `revenue_currency_code`). `update_uet_tag` renames/redescribes
  a tag.
- *Location (ZIP/geo) targeting* — `add_location_targets`, `remove_location_targets`,
  `set_location_intent` (presence — `PeopleIn` — vs. search-interest targeting; one criterion
  per campaign, updated in place).
- *Ad scheduling (dayparting)* — `add_ad_schedules`, `remove_ad_schedules` (day + time windows at
  15-minute granularity; times run in the campaign time zone unless `use_searcher_time_zone` is
  set). `update_campaign` accepts `time_zone` to set the zone those schedules run in.
- *Device bid adjustments* — `set_device_bid_adjustment(campaign_id, device, bid_adjustment)` sets
  a per-device modifier (-100 to 900 percent; -100 excludes the device). Microsoft calls mobile
  **Smartphones** (there is no "Mobile"); "Computers" is desktop/laptop. Device criterions are
  created as a set, so the first call also creates the other two at a neutral 0.
- *Bulk API* — `bulk_upload`.

The `update_*` tools patch in place: only the fields you pass change. Prefer them over
recreate-and-pause when an entity already exists.

### Tool discovery (`TOOL_SEARCH`)

With `TOOL_SEARCH=true`, the server lists only a few pinned orientation tools
(`account_health`, `search_accounts`, `get_campaigns`, `run_performance_report`, plus the auth
tools) alongside two synthetic tools: `search_tools(query)` (BM25 over names, descriptions, and
parameters) and `call_tool(name, arguments)`. The rest of the catalog is discovered on demand
instead of loaded upfront — useful as the tool count grows. Hidden tools keep their full typed
schemas, and because search runs through the normal pipeline, the `READ_ONLY` gate still applies:
write tools aren't registered in read-only mode, so they're neither listed nor discoverable. This
is FastMCP's stable `BM25SearchTransform` — no code execution, no sandbox.

## Architecture

```
src/microsoft_ads_mcp/
  config.py            # pydantic-settings; all env config
  server.py            # builds FastMCP, lifespan-manages the client, registers tools
  api/
    auth.py            # OAuth flow + hardened token store
    client.py          # wraps msads ServiceClient(s); the single dispatch point
    errors.py          # translate openapi_client exceptions -> MsAdsApiError
  domain/
    entities.py        # lean Pydantic summary/report models for tool outputs
  services/
    accounts.py        # user/account reads (CustomerManagementService)
    account_properties.py  # account-level URL options (CampaignManagementService AccountProperties)
    campaigns.py       # hierarchy + list reads
    mutations.py       # create/update/delete for campaigns, ad groups, ads, keywords
    negatives.py       # negative-keyword add/list/remove
    extensions.py      # ad extensions (call/callout/sitelink)
    conversions.py     # conversion goals + UET tags
    criteria.py        # location (ZIP/geo) targeting via campaign criterions
    geo.py             # ZIP -> LocationId resolution (cached geo-locations file)
    bulk.py            # Bulk API upload/download (submit/poll)
    reporting.py       # submit/poll/download/parse
  tools/
    health.py read_tools.py write_tools.py reporting_tools.py auth_tools.py  # READ_ONLY-gated
```

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run pytest -q
# or all at once:
bash scripts/ci.sh
```

### MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is a browser UI for
calling the server's tools by hand — the fastest way to exercise a tool while iterating
locally. FastMCP ships an integration that launches it (with auto-reload on file changes):

```bash
# Run the package as a module (-m) so its relative imports resolve; --with-editable .
# installs this package into the Inspector's ephemeral env.
uv run fastmcp dev inspector microsoft_ads_mcp -m --with-editable .
```

This prints a `http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=...` URL — open it, connect, and
call `account_health` first. To test the exact `python -m` entrypoint an MCP client uses,
run the standalone Inspector against the real command instead:

```bash
npx @modelcontextprotocol/inspector uv run python -m microsoft_ads_mcp
```

Either way, credentials load from `.env`. Write tools only appear when `READ_ONLY=false` —
set it in `.env`, or (for the standalone Inspector) in its env panel before connecting.

## License

MIT — see [LICENSE](LICENSE).
