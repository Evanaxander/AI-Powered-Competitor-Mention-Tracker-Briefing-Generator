import os
import requests
import anthropic
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
from datetime import datetime, timezone
import openai
load_dotenv()

app = Flask(__name__)

# ── API Clients ──────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
openrouter_client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

# ── HN Algolia API — Two Endpoints Explained ──────────────────────────────────
#
# The Hacker News Algolia API has two distinct search endpoints:
#
#   1. /search          — ranks results by RELEVANCE (best match first)
#                         Good for: finding the most discussed/upvoted mentions
#
#   2. /search_by_date  — ranks results by DATE (newest first)
#                         Good for: finding the most recent mentions
#
# We use BOTH so we get a complete picture:
#   - Source 1 (HN Stories): high-signal, upvoted posts about the competitor
#   - Source 2 (HN Comments): raw community discussion and opinions
#
# Both are 100% free, no API key, no account needed.
# Base URL: https://hn.algolia.com/api/v1/
# Docs: https://hn.algolia.com/api


# ── Data Source 1: HN Stories (sorted by relevance) ──────────────────────────
# Fetches full story posts that mention the competitor.
# These are submitted links or Ask HN posts — higher quality, more context.

def fetch_hn_stories(competitor: str, limit: int = 10) -> list[dict]:
    params = {
        "query": competitor,
        "tags": "story",        # only top-level stories, not comments
        "hitsPerPage": limit
        # endpoint: /search = sorted by relevance score (points + recency combo)
    }

    response = requests.get(
        "https://hn.algolia.com/api/v1/search",
        params=params,
        timeout=10
    )
    response.raise_for_status()

    hits = response.json().get("hits", [])
    mentions = []

    for hit in hits:
        title = hit.get("title") or "Untitled HN Story"
        body  = hit.get("story_text") or ""   # Ask HN posts have body text; links don't

        mentions.append({
            "source": "HN Stories",
            "title": title,
            "body": body[:500],               # cap to 500 chars to save LLM tokens
            "score": hit.get("points", 0),
            "url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
            "created_at": hit.get("created_at", "")[:10]
        })

    return mentions


# ── Data Source 2: HN Comments (sorted by date, newest first) ────────────────
# Fetches individual comments mentioning the competitor.
# Comments are where real opinions live — complaints, comparisons, recommendations.
# We use /search_by_date here so we get the freshest community reactions.

def fetch_hn_comments(competitor: str, limit: int = 10) -> list[dict]:
    params = {
        "query": competitor,
        "tags": "comment",      # only comments, not stories
        "hitsPerPage": limit
        # endpoint: /search_by_date = sorted purely by timestamp (newest first)
    }

    response = requests.get(
        "https://hn.algolia.com/api/v1/search_by_date",
        params=params,
        timeout=10
    )
    response.raise_for_status()

    hits = response.json().get("hits", [])
    mentions = []

    for hit in hits:
        # Comments don't have their own title — use the parent story title instead
        title = hit.get("story_title") or "HN Comment"
        body  = hit.get("comment_text") or ""

        mentions.append({
            "source": "HN Comments",
            "title": title,
            "body": body[:500],
            "score": hit.get("points", 0),
            "url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
            "created_at": hit.get("created_at", "")[:10]
        })

    return mentions


# ── LLM: Generate Briefing ────────────────────────────────────────────────────
# This is the core of the tool. We format all raw mentions into a structured
# prompt and ask Claude to generate the briefing in Markdown.
#
# Key prompt design decisions:
# 1. We pass data per-competitor so Claude can reason about each separately.
# 2. We explicitly define the output schema (sections + format) to get consistent results.
# 3. We cap mention bodies to 500 chars upstream to avoid hitting token limits.
# 4. Temperature is set low (0.3) for factual, consistent output.

def generate_briefing(competitors_data: dict) -> str:
    # Build a structured text block from all mentions
    mentions_text = ""
    for competitor, mentions in competitors_data.items():
        mentions_text += f"\n\n## {competitor} ({len(mentions)} mentions)\n"
        if not mentions:
            mentions_text += "No mentions found.\n"
            continue
        for m in mentions:
            mentions_text += (
                f"\n- [{m['source']}] {m['title']}\n"
                f"  Body: {m['body']}\n"
                f"  Score/Upvotes: {m['score']} | URL: {m['url']} | Date: {m['created_at']}\n"
            )

    prompt = f"""You are a competitive intelligence analyst for Deskflow, a B2B SaaS IT service management platform.

Below is raw data scraped from Hacker News Stories (relevance-ranked) and Hacker News Comments (date-ranked) mentioning our competitors.

{mentions_text}

Generate a structured internal competitive intelligence briefing in Markdown with EXACTLY these sections:

# Competitive Intelligence Briefing
*Generated: {datetime.now().strftime("%B %d, %Y")}*

## Executive Summary
2-3 sentences. What is the overall competitive landscape signal this week?

---

## Per-Competitor Analysis

For EACH competitor, write:

### [Competitor Name]
**Sentiment:** (Positive / Negative / Mixed / Neutral) — one sentence why

**Top Themes & Complaints:**
- Bullet 1
- Bullet 2
- Bullet 3 (max 5 bullets)

**Notable Quotes / Threads Worth Flagging:**
> Quote or thread summary here (include source URL)

---

## Positioning Opportunities for Deskflow
Based on the competitor weaknesses and user complaints above, list 3-5 specific angles Deskflow can exploit in messaging, content, or sales conversations.

---

## Risk Flags
Anything competitors are doing well that Deskflow should be aware of or respond to.

Rules:
- Be specific. Reference actual complaints, quotes, or themes from the data.
- If a competitor has no mentions, note it briefly and move on.
- Keep each competitor section concise — this is an internal briefing, not an essay.
- Output only the Markdown. No preamble, no explanation.
"""

    response = openrouter_client.chat.completions.create(
        model="anthropic/claude-3.5-haiku",  # free tier on OpenRouter
        max_tokens=2000,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}]
)
    return response.choices[0].message.content


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    """
    Main endpoint. Receives competitor list, fetches mentions from BOTH HN sources,
    passes everything to Claude, returns the briefing as JSON.

    Flow:
      1. For each competitor: call fetch_hn_stories() + fetch_hn_comments()
      2. Merge into one list per competitor
      3. Pass all data to generate_briefing() which calls Claude
      4. Return briefing + stats to the frontend
    """
    data = request.get_json()
    competitors = data.get("competitors", [])

    if not competitors:
        return jsonify({"error": "No competitors provided."}), 400

    competitors_data = {}
    fetch_errors = []

    for competitor in competitors:
        mentions = []

        # Source 1: HN Stories (relevance-ranked)
        try:
            stories = fetch_hn_stories(competitor, limit=8)
            mentions.extend(stories)
            print(f"[INFO] {competitor}: fetched {len(stories)} HN stories")
        except Exception as e:
            fetch_errors.append(f"HN Stories fetch failed for '{competitor}': {str(e)}")
            print(f"[ERROR] {fetch_errors[-1]}")

        # Source 2: HN Comments (date-ranked, newest first)
        try:
            comments = fetch_hn_comments(competitor, limit=8)
            mentions.extend(comments)
            print(f"[INFO] {competitor}: fetched {len(comments)} HN comments")
        except Exception as e:
            fetch_errors.append(f"HN Comments fetch failed for '{competitor}': {str(e)}")
            print(f"[ERROR] {fetch_errors[-1]}")

        competitors_data[competitor] = mentions

    # If ALL sources failed for ALL competitors, bail out early
    total_mentions = sum(len(v) for v in competitors_data.values())
    if total_mentions == 0 and fetch_errors:
        return jsonify({
            "error": "All data fetches failed. Check your internet connection.",
            "fetch_errors": fetch_errors
        }), 500

    # Generate briefing via Claude
    try:
        briefing = generate_briefing(competitors_data)
    except Exception as e:
        return jsonify({
            "error": f"LLM generation failed: {str(e)}",
            "fetch_errors": fetch_errors
        }), 500

    return jsonify({
        "briefing": briefing,
        "total_mentions": total_mentions,
        "fetch_errors": fetch_errors,
        "competitors": {k: len(v) for k, v in competitors_data.items()}
    })


@app.route("/download", methods=["POST"])
def download():
    """
    Accepts the briefing text and serves it as a downloadable .md file.
    Simple approach: no file storage needed, just stream the string as a response.
    """
    data = request.get_json()
    briefing = data.get("briefing", "")

    if not briefing:
        return jsonify({"error": "No briefing to download."}), 400

    filename = f"competitive_briefing_{datetime.now().strftime('%Y%m%d_%H%M')}.md"

    return Response(
        briefing,
        mimetype="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5000)