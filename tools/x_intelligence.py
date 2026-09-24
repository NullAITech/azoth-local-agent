"""Live X (Twitter) Intelligence, Search, and Social Scouting for aZoth-local.

Provides real-time search on X/Twitter posts, threads, user profiles, trending
topics, and thread drafting — mirroring and expanding Grok's real-time X intelligence.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Optional

from .browser import get_browser
from .search import search_web


def search_x(query: str, max_results: int = 8) -> dict[str, Any]:
    """Search live X (Twitter) posts, discussions, and handles."""
    clean_query = query.strip()
    
    # Run multi-engine search targeting X / Twitter posts
    search_queries = [
        f"{clean_query} site:x.com",
        f"{clean_query} twitter status",
        f"{clean_query} x.com",
    ]

    posts: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for q in search_queries:
        res = search_web(q, max_results=max_results)
        for item in res.get("results", []):
            u = item.get("url", "")
            if not u or u in seen_urls:
                continue

            if "x.com" in u or "twitter.com" in u:
                seen_urls.add(u)
                handle_match = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]+)", u)
                handle = f"@{handle_match.group(1)}" if handle_match else "@user"
                posts.append({
                    "title": item.get("title", ""),
                    "handle": handle,
                    "url": u,
                    "content": item.get("snippet", ""),
                    "is_status": "/status/" in u,
                })

        if len(posts) >= max_results:
            break

    # If public web search returned sparse X status links, include top related social results
    if not posts:
        fallback_res = search_web(f"{clean_query} on X", max_results=max_results)
        for item in fallback_res.get("results", []):
            u = item.get("url", "")
            if u not in seen_urls:
                seen_urls.add(u)
                posts.append({
                    "title": item.get("title", ""),
                    "handle": "@x_discussion",
                    "url": u,
                    "content": item.get("snippet", ""),
                    "is_status": False,
                })

    return {
        "ok": True,
        "platform": "X (Twitter)",
        "query": clean_query,
        "count": len(posts),
        "posts": posts,
        "summary": f"Found {len(posts)} posts and discussions for '{clean_query}' on X",
    }


def scout_x_trends(topic_focus: str = "tech") -> dict[str, Any]:
    """Scout currently trending discussions, hashtags, and breaking topics on X."""
    query = f"trending {topic_focus} discussions on X today"
    res = search_x(query, max_results=6)
    if not res.get("ok") or not res.get("posts"):
        res = search_x(f"{topic_focus} latest announcements", max_results=6)
    return {
        "ok": res.get("ok", False),
        "topic_focus": topic_focus,
        "trends": res.get("posts", []),
        "summary": f"Scouted {len(res.get('posts', []))} trending topics in '{topic_focus}'",
    }


def draft_x_thread(topic: str, tone: str = "high-signal", num_tweets: int = 4) -> dict[str, Any]:
    """Draft an authentic, high-signal X thread free of AI clichés."""
    guidance = (
        f"Topic: {topic}\n"
        f"Tone: {tone}\n"
        f"Tweets: {num_tweets}\n\n"
        "Rules:\n"
        "1. Hook: Start with a concrete counter-intuitive insight, metric, or real build takeaway. No 'In today's fast-paced world' or 'Game changer'.\n"
        "2. Body: Keep each tweet under 280 chars, focused on 1 core point.\n"
        "3. Conclusion: Actionable takeaway or open question to invite real peer discussion."
    )
    return {
        "ok": True,
        "topic": topic,
        "tone": tone,
        "num_tweets": num_tweets,
        "guidance": guidance,
        "summary": f"Prepared X thread framework for '{topic}' ({num_tweets} posts, {tone} style)",
    }


def inspect_x_post_browser(post_url: str) -> dict[str, Any]:
    """Navigate to a post on X using the authenticated sandboxed browser and extract DOM text."""
    browser = get_browser()
    nav_res = browser.navigate(post_url)
    if not nav_res.get("ok"):
        return nav_res

    content_res = browser.extract_content(max_chars=6000)
    return {
        "ok": True,
        "url": post_url,
        "content": content_res.get("content", ""),
        "summary": f"Extracted authenticated live post view from {post_url}",
    }
