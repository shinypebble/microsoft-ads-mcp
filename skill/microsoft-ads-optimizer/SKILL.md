---
name: microsoft-ads-optimizer
description: Playbook for managing and reporting on a Microsoft Advertising account via the microsoft-ads MCP server.
---

# Microsoft Advertising optimizer

A playbook for operating a single Microsoft Advertising (Bing Ads) account through the
`microsoft-ads` MCP server.

## Start here

1. Call `account_health` to confirm credentials and learn whether writes are enabled
   (`read_only`). Branch on `auth_state` / `needs_interactive_auth`: only run the interactive
   sign-in when `needs_interactive_auth` is true (`no_token` / `token_expired`). A
   `token_rejected` or `account_inactive` state is **not** fixed by re-auth — re-consent can
   clobber a shared token; check the developer token / account binding instead.
2. Call `search_accounts` to find the account/customer ids if they are not pre-configured. Use
   `set_active_account(account_id)` to switch which account subsequent calls hit, then
   re-confirm with `account_health` before writing.

## Reading the account

- `get_campaigns` → `get_ad_groups(campaign_id)` → `get_keywords(ad_group_id)` /
  `get_ads(ad_group_id)` walks the hierarchy top-down. `get_ads` returns the RSA copy
  (`headlines` / `descriptions` / `path1` / `path2`) so you can show or clone an ad.
- `get_budgets` gives a per-campaign budget view.
- `run_performance_report(report_type, date_range)` returns parsed rows. Use
  `report_type="search_query"` to mine actual search terms for new keywords or negatives,
  `"keyword"` for quality-score and CTR triage, and `"geographic"` for location performance.
  Pass `start_date`/`end_date` ("YYYY-MM-DD") for a custom window and `campaign_id`/`ad_group_id`
  to scope to one entity (e.g. confirm a repointed URL is serving for one campaign).
- `get_negative_keywords`, `get_ad_extensions`, `get_conversion_goals`, `get_uet_tags`, and
  `get_location_targets(campaign_id)` read the rest of the model.

## Building from scratch (only when read_only is false)

- New campaigns, ad groups, and ads are always created **PAUSED**. Review, then call
  `update_campaign_status(campaign_id, "Active")` (or `update_campaign(..., status="Active")`).
- A typical build: `create_campaign` → `create_ad_group` → `add_keywords` →
  `create_responsive_search_ad` → verify with the read tools → activate.
- Headlines are capped at 30 chars and descriptions at 90; provide 3-15 headlines and 2-4
  descriptions for a strong RSA.

## Editing in place (only when read_only is false)

- Rename / rebudget / restatus: `update_campaign`, `update_ad_group`, `update_keyword`. Only the
  fields you pass change (the rest are untouched).
- Repoint a Final URL or refresh copy without recreating the ad:
  `update_responsive_search_ad(ad_group_id, ad_id, final_url=...)`. Get `ad_id` from `get_ads`.
- Tracking templates / Final URL suffixes are supported on campaign, ad group, and ad
  create/update (`tracking_url_template`, `final_url_suffix`) — set the template once instead of
  editing every URL.
- Negatives: `add_negative_keywords(entity_id, keywords, entity_type)` (Campaign or AdGroup),
  `remove_negative_keywords` (by id — resolve with `get_negative_keywords` first).
- Extensions: `add_call_extension` / `add_callout_extension` / `add_sitelink_extension`
  create-and-associate to a campaign/ad group; `update_call_extension(ad_extension_id,
  phone_number=..., country_code="US")` edits one in place; `delete_ad_extension(ids)` removes
  extension objects. Note `get_ad_extensions` only lists extensions *associated* at the queried
  scope, so a freshly created, unattached extension won't appear there.
- Conversion goals / UET: `update_conversion_goal(goal_id, name)`, `update_uet_tag(tag_id, ...)`.
- ZIP/location targeting: `resolve_postal_codes(["98101", ...])` → `add_location_targets(
  campaign_id, location_ids, exclude=False)`; remove by criterion id from `get_location_targets`.
- Cleanup: `delete_campaign` / `delete_ad_group` / `delete_ad` / `delete_keyword`.
- Atomic bulk apply/export: `bulk_upload(entity_records)` and `bulk_download()`.

## Cautions

- Always confirm the target `campaign_id` / `ad_group_id` (and the active account) with a read
  tool before mutating.
- Prefer editing in place (`update_*`) over recreate-and-pause when an entity already exists.
- `MutationResult.partial_errors` is non-empty when the API rejected part of a batch — surface
  those messages rather than assuming success from a non-empty `ids` list.
