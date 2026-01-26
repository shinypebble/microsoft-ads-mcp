# Microsoft Ads MCP Server

A Model Context Protocol (MCP) server for Microsoft Advertising (Bing Ads / DuckDuckGo Ads). This server enables AI assistants to create, manage, and report on Microsoft Advertising campaigns programmatically.

## Features

### Authentication
- OAuth 2.0 authentication flow with token persistence
- Automatic token refresh

### Campaign Management
- **Campaigns**: Create, list, pause/activate search campaigns
- **Ad Groups**: Create and list ad groups within campaigns
- **Keywords**: Add keywords with Broad, Phrase, or Exact match types
- **Ads**: Create Responsive Search Ads (RSAs) with multiple headlines and descriptions

### Reporting
- Campaign performance reports
- Keyword performance reports
- Search query reports (actual search terms)
- Geographic performance reports
- Async report generation with polling

### Account Management
- List all accessible accounts
- View campaign budgets
- Label management

## Prerequisites

1. **Microsoft Advertising Account**: Sign up at [ads.microsoft.com](https://ads.microsoft.com)
2. **Developer Token**: Apply at [Microsoft Advertising Developer Portal](https://developers.ads.microsoft.com/)
3. **Azure AD App Registration**: Create an app in [Azure Portal](https://portal.azure.com) with:
   - Redirect URI: `https://login.microsoftonline.com/common/oauth2/nativeclient`
   - API permissions: Microsoft Advertising API

## Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/microsoft-ads-mcp-server.git
cd microsoft-ads-mcp-server

# Install dependencies
pip install -r requirements.txt
```

## Configuration

### Environment Variables

Create a `.env` file or set these environment variables:

```bash
MICROSOFT_ADS_DEVELOPER_TOKEN=your_developer_token
MICROSOFT_ADS_CLIENT_ID=your_azure_app_client_id
MICROSOFT_ADS_CUSTOMER_ID=your_customer_id      # Optional, discovered during auth
MICROSOFT_ADS_ACCOUNT_ID=your_account_id        # Optional, discovered during auth
```

### Token Storage

Tokens are stored in `~/.config/microsoft-ads/tokens.json` after authentication.

## Usage

### With Claude Code / mcporter

Add to your `~/.mcporter/mcporter.json`:

```json
{
  "mcpServers": {
    "microsoft-ads": {
      "command": "python3",
      "args": ["/path/to/microsoft-ads-mcp-server/server.py"],
      "type": "stdio",
      "env": {
        "MICROSOFT_ADS_DEVELOPER_TOKEN": "your_token",
        "MICROSOFT_ADS_CLIENT_ID": "your_client_id"
      }
    }
  }
}
```

### Standalone

```bash
python server.py
```

## Authentication Flow

1. Call `get_auth_url()` to get the OAuth URL
2. Open the URL in a browser and sign in with your Microsoft account
3. After authorization, copy the redirect URL (starts with `https://login.microsoftonline.com/common/oauth2/nativeclient?code=...`)
4. Call `complete_auth(redirect_url)` with the full redirect URL
5. Your tokens are now saved and will auto-refresh

## Available Tools

### Authentication
| Tool | Description |
|------|-------------|
| `get_auth_url()` | Get OAuth URL for sign-in |
| `complete_auth(redirect_url)` | Complete OAuth with redirect URL |

### Accounts
| Tool | Description |
|------|-------------|
| `search_accounts()` | List all accessible advertising accounts |

### Campaigns
| Tool | Description |
|------|-------------|
| `get_campaigns(include_deleted?)` | List all campaigns |
| `create_campaign(name, daily_budget, description?)` | Create a search campaign (paused by default) |
| `update_campaign_status(campaign_id, status)` | Set campaign to Active or Paused |

### Ad Groups
| Tool | Description |
|------|-------------|
| `get_ad_groups(campaign_id)` | List ad groups in a campaign |
| `create_ad_group(campaign_id, name, cpc_bid?)` | Create an ad group |

### Keywords
| Tool | Description |
|------|-------------|
| `get_keywords(ad_group_id)` | List keywords in an ad group |
| `add_keywords(ad_group_id, keywords, match_type?, default_bid?)` | Add keywords (comma-separated) |

### Ads
| Tool | Description |
|------|-------------|
| `get_ads(ad_group_id)` | List ads in an ad group |
| `create_responsive_search_ad(ad_group_id, final_url, headlines, descriptions, path1?, path2?)` | Create an RSA |

### Reporting
| Tool | Description |
|------|-------------|
| `submit_campaign_performance_report(date_range?, columns?)` | Submit campaign report request |
| `submit_keyword_performance_report(date_range?, columns?)` | Submit keyword report request |
| `submit_search_query_report(date_range?, columns?)` | Submit search terms report request |
| `submit_geographic_report(date_range?, columns?)` | Submit geo report request |
| `poll_report_status(report_id?)` | Check report status and get download URL |

### Other
| Tool | Description |
|------|-------------|
| `get_budgets()` | View campaign budgets |
| `get_labels(label_ids?)` | Get label information |

## Example Workflow

```python
# 1. Authenticate (first time only)
get_auth_url()
# Open URL in browser, sign in, copy redirect URL
complete_auth("https://login.microsoftonline.com/common/oauth2/nativeclient?code=...")

# 2. Check your account
search_accounts()

# 3. Create a campaign
create_campaign(name="My Search Campaign", daily_budget=20)

# 4. Create an ad group
create_ad_group(campaign_id=123456, name="Product Keywords", cpc_bid=1.50)

# 5. Add keywords
add_keywords(
    ad_group_id=789012,
    keywords="buy widgets, widget store, best widgets",
    match_type="Phrase",
    default_bid=1.25
)

# 6. Create an ad
create_responsive_search_ad(
    ad_group_id=789012,
    final_url="https://example.com/widgets",
    headlines="Buy Widgets Online|Best Widget Store|Free Shipping on Widgets",
    descriptions="Shop our huge selection of widgets. Free shipping on orders over $50.|Quality widgets at great prices. Order today!"
)

# 7. Activate the campaign
update_campaign_status(campaign_id=123456, status="Active")

# 8. Check performance later
submit_campaign_performance_report(date_range="LastWeek")
poll_report_status()
```

## Why Microsoft Advertising?

- **DuckDuckGo Integration**: Microsoft Advertising powers DuckDuckGo search ads, reaching privacy-conscious users
- **Lower CPCs**: Often 30-50% cheaper than Google Ads for similar keywords
- **Bing + Yahoo + AOL**: Access to the Microsoft Search Network
- **Import from Google**: Easy migration of existing Google Ads campaigns

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- Uses the [Bing Ads Python SDK](https://github.com/BingAds/BingAds-Python-SDK)
