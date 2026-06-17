---
name: microsoft-ads-optimizer
description: Playbook for managing and reporting on a Microsoft Advertising account via the microsoft-ads MCP server.
---

# Microsoft Advertising optimizer

A playbook for operating a single Microsoft Advertising (Bing Ads) account through the
`microsoft-ads` MCP server.

## Start here

1. Call `account_health` to confirm credentials and learn whether writes are enabled
   (`read_only`). If it reports an auth failure and you have no refresh token, run
   `get_auth_url` → open the URL → `complete_auth(redirect_url)` once.
2. Call `search_accounts` to find the account/customer ids if they are not pre-configured.

## Reading the account

- `get_campaigns` → `get_ad_groups(campaign_id)` → `get_keywords(ad_group_id)` /
  `get_ads(ad_group_id)` walks the hierarchy top-down.
- `get_budgets` gives a per-campaign budget view.
- `run_performance_report(report_type, date_range)` returns parsed rows. Use
  `report_type="search_query"` to mine actual search terms for new keywords or negatives,
  `"keyword"` for quality-score and CTR triage, and `"geographic"` for location performance.

## Making changes (only when read_only is false)

- New campaigns, ad groups, and ads are always created **PAUSED**. Review, then call
  `update_campaign_status(campaign_id, "Active")` to launch.
- A typical build: `create_campaign` → `create_ad_group` → `add_keywords` →
  `create_responsive_search_ad` → verify with the read tools → activate.
- Headlines are capped at 30 chars and descriptions at 90; provide 3-15 headlines and 2-4
  descriptions for a strong RSA.

## Cautions

- Always confirm the target `campaign_id` / `ad_group_id` with a read tool before mutating.
- `MutationResult.partial_errors` is non-empty when the API rejected part of a batch — surface
  those messages rather than assuming success from a non-empty `ids` list.
