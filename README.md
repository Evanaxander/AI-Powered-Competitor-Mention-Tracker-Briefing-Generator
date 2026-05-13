# Deskflow — Competitor Mention Tracker & Briefing Generator

Automates competitive intelligence by pulling mentions from Reddit and Hacker News,
then generating a structured briefing via Claude AI.

## Project Structure

```
competitor-tracker/
├── app.py              # Flask backend — all API logic
├── requirements.txt
├── .env                # API keys (never commit)
├── templates/
│   └── index.html      # Single-page frontend
└── README.md
```

## Setup

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get your API keys

**Anthropic (Claude):**
- Go to console.anthropic.com
- Create an API key

**Reddit:**
- Go to reddit.com/prefs/apps
- Click "Create App" → select "script"
- Redirect URI: `http://localhost:8080` (anything works)
- Copy the Client ID (shown under app name) and Client Secret

### 3. Create `.env`

```
ANTHROPIC_API_KEY=sk-ant-...
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT=CompetitorTracker/1.0
```

### 4. Run

```bash
python app.py
```

Open http://localhost:5000

## How It Works

1. User enters competitor names (defaults: Freshservice, Jira Service Management, SysAid)
2. Backend authenticates with Reddit OAuth (client_credentials flow — no user login needed)
3. Fetches recent posts/comments from Reddit search + Hacker News Algolia API
4. All mentions are passed to Claude with a structured prompt
5. Claude returns a Markdown briefing: sentiment, themes, quotes, positioning opportunities
6. Frontend renders the Markdown and offers download

## Key Architecture Decisions

- **Two data sources:** Reddit (authenticated search API) + HN Algolia (free, no auth)
- **Token capping:** Mention bodies capped at 500 chars to avoid LLM token overflow
- **Graceful degradation:** If Reddit auth fails, still runs with HN data only
- **Low temperature (0.3):** Claude is set to low creativity for factual, consistent output
- **Download:** Briefing streamed directly as `.md` — no file stored on server

## Error Handling

| Scenario | Behavior |
|---|---|
| Reddit auth fails | Continues with HN data only, logs warning |
| Individual source fetch fails | Logs error, continues with other source |
| No mentions found | Passed to LLM with "no data" note, still generates briefing |
| LLM fails | Returns 500 with error message displayed in UI |
| Empty competitor list | Blocked at frontend before request is made |
