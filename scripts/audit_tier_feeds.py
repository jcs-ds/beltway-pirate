#!/usr/bin/env python3
"""
Audit the 37 curated RSS feeds to verify they return data.
Uses the same headers as the backend RSS proxy.
"""

import asyncio
import httpx
import feedparser
import json
from datetime import datetime

# Browser-like headers (same as backend)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/rss+xml, application/xml, text/xml, application/atom+xml, */*',
    'Accept-Language': 'en-US,en;q=0.9',
}

# All 37 feeds from the tier hierarchy
FEEDS = [
    # TIER 1: ESSENTIAL (15 feeds)
    {"id": "c4isrnet", "name": "C4ISRNET", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/?outputType=xml", "tier": "tier1"},
    {"id": "c4isrnet-electronic-warfare", "name": "C4ISRNET EW", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/category/electronic-warfare/?outputType=xml", "tier": "tier1"},
    {"id": "c4isrnet-cyber", "name": "C4ISRNET Cyber", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/category/cyber/?outputType=xml", "tier": "tier1"},
    {"id": "c4isrnet-unmanned", "name": "C4ISRNET Unmanned", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/category/unmanned/?outputType=xml", "tier": "tier1"},
    {"id": "c4isrnet-ai", "name": "C4ISRNET AI", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/category/artificial-intelligence/?outputType=xml", "tier": "tier1"},
    {"id": "breaking-defense", "name": "Breaking Defense", "url": "https://breakingdefense.com/feed/", "tier": "tier1"},
    {"id": "defense-scoop", "name": "Defense Scoop", "url": "https://defensescoop.com/feed/", "tier": "tier1"},
    {"id": "the-war-zone", "name": "The War Zone", "url": "https://twz.com/feed/", "tier": "tier1"},
    {"id": "defense-one", "name": "Defense One", "url": "https://www.defenseone.com/rss/all/", "tier": "tier1"},
    {"id": "defense-one-technology", "name": "Defense One Tech", "url": "https://defenseone.com/rss/technology", "tier": "tier1"},
    {"id": "defense-news", "name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", "tier": "tier1"},
    {"id": "defense-news-pentagon", "name": "Defense News Pentagon", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/pentagon/?outputType=xml", "tier": "tier1"},
    {"id": "defense-news-congress", "name": "Defense News Congress", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/congress/?outputType=xml", "tier": "tier1"},
    {"id": "real-clear-defense", "name": "Real Clear Defense", "url": "https://www.realcleardefense.com/index.xml", "tier": "tier1"},
    {"id": "war-on-the-rocks", "name": "War on the Rocks", "url": "https://warontherocks.com/feed/", "tier": "tier1"},

    # TIER 2A: INSTITUTES & THINK TANKS (12 feeds)
    {"id": "csis", "name": "CSIS", "url": "https://www.csis.org/analysis/feed", "tier": "tier2a"},
    {"id": "rand", "name": "RAND", "url": "https://www.rand.org/pubs/new.xml", "tier": "tier2a"},
    {"id": "cnas", "name": "CNAS", "url": "https://www.cnas.org/feed", "tier": "tier2a"},
    {"id": "atlantic-council", "name": "Atlantic Council", "url": "https://www.atlanticcouncil.org/feed/", "tier": "tier2a"},
    {"id": "hudson-institute", "name": "Hudson Institute", "url": "https://www.hudson.org/feed", "tier": "tier2a"},
    {"id": "heritage-foundation", "name": "Heritage Foundation", "url": "https://www.dailysignal.com/feed/", "tier": "tier2a"},
    {"id": "aei", "name": "AEI", "url": "https://www.aei.org/feed/", "tier": "tier2a"},
    {"id": "brookings", "name": "Brookings", "url": "https://www.brookings.edu/feed/", "tier": "tier2a"},
    {"id": "cfr", "name": "CFR", "url": "https://feeds.feedburner.com/cfr_main", "tier": "tier2a"},
    {"id": "modern-war-institute", "name": "Modern War Institute", "url": "https://mwi.westpoint.edu/feed/", "tier": "tier2a"},
    {"id": "isw", "name": "ISW", "url": "https://www.iswresearch.org/feeds/posts/default?alt=rss", "tier": "tier2a"},
    {"id": "long-war-journal", "name": "Long War Journal", "url": "https://feeds.feedburner.com/LongWarJournal", "tier": "tier2a"},

    # TIER 2B: DOMAIN & SERVICE SPECIFIC (10 feeds)
    {"id": "usni-news", "name": "USNI News", "url": "https://news.usni.org/feed", "tier": "tier2b"},
    {"id": "air-and-space-forces-magazine", "name": "Air & Space Forces", "url": "https://www.airandspaceforces.com/feed/", "tier": "tier2b"},
    {"id": "army-times", "name": "Army Times", "url": "https://www.armytimes.com/arc/outboundfeeds/rss/?outputType=xml", "tier": "tier2b"},
    {"id": "navy-times", "name": "Navy Times", "url": "https://www.navytimes.com/arc/outboundfeeds/rss/?outputType=xml", "tier": "tier2b"},
    {"id": "air-force-times", "name": "Air Force Times", "url": "https://www.airforcetimes.com/arc/outboundfeeds/rss/?outputType=xml", "tier": "tier2b"},
    {"id": "marine-corps-times", "name": "Marine Corps Times", "url": "https://www.marinecorpstimes.com/arc/outboundfeeds/rss/?outputType=xml", "tier": "tier2b"},
    {"id": "spacenews", "name": "SpaceNews", "url": "https://spacenews.com/feed/", "tier": "tier2b"},
    {"id": "defense-news-naval", "name": "Defense News Naval", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/naval/?outputType=xml", "tier": "tier2b"},
    {"id": "defense-news-space", "name": "Defense News Space", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/space/?outputType=xml", "tier": "tier2b"},
    {"id": "bellingcat", "name": "Bellingcat", "url": "https://www.bellingcat.com/feed/", "tier": "tier2b"},
]

async def test_feed(client: httpx.AsyncClient, feed: dict) -> dict:
    """Test a single feed and return results."""
    result = {
        "id": feed["id"],
        "name": feed["name"],
        "tier": feed["tier"],
        "url": feed["url"],
        "status": "UNKNOWN",
        "http_status": None,
        "article_count": 0,
        "error": None,
        "latest_article": None,
    }

    try:
        response = await client.get(feed["url"], headers=HEADERS, follow_redirects=True)
        result["http_status"] = response.status_code

        if response.status_code != 200:
            result["status"] = f"HTTP_{response.status_code}"
            result["error"] = f"HTTP {response.status_code}"
            return result

        # Parse the feed
        parsed = feedparser.parse(response.text)

        if parsed.bozo and not parsed.entries:
            result["status"] = "PARSE_ERROR"
            result["error"] = str(parsed.bozo_exception)[:100] if parsed.bozo_exception else "Parse failed"
            return result

        article_count = len(parsed.entries)
        result["article_count"] = article_count

        if article_count == 0:
            result["status"] = "EMPTY"
            result["error"] = "No articles found"
            return result

        # Get latest article info
        if parsed.entries:
            latest = parsed.entries[0]
            result["latest_article"] = {
                "title": latest.get("title", "")[:80],
                "date": latest.get("published") or latest.get("updated") or "Unknown"
            }

        result["status"] = "OK"
        return result

    except httpx.TimeoutException:
        result["status"] = "TIMEOUT"
        result["error"] = "Request timed out"
        return result
    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)[:100]
        return result

async def main():
    print("=" * 70)
    print("RSS FEED AUDIT - 37 Curated Feeds")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    results = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Process in batches of 5
        for i in range(0, len(FEEDS), 5):
            batch = FEEDS[i:i+5]
            print(f"Testing batch {i//5 + 1}/{(len(FEEDS) + 4)//5}...")

            tasks = [test_feed(client, feed) for feed in batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)

            # Small delay between batches
            if i + 5 < len(FEEDS):
                await asyncio.sleep(0.5)

    # Organize results
    tier1_ok = [r for r in results if r["tier"] == "tier1" and r["status"] == "OK"]
    tier1_fail = [r for r in results if r["tier"] == "tier1" and r["status"] != "OK"]
    tier2a_ok = [r for r in results if r["tier"] == "tier2a" and r["status"] == "OK"]
    tier2a_fail = [r for r in results if r["tier"] == "tier2a" and r["status"] != "OK"]
    tier2b_ok = [r for r in results if r["tier"] == "tier2b" and r["status"] == "OK"]
    tier2b_fail = [r for r in results if r["tier"] == "tier2b" and r["status"] != "OK"]

    print()
    print("=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print()

    # Tier 1
    print(f"TIER 1 (Essential): {len(tier1_ok)}/15 working")
    print("-" * 40)
    for r in tier1_ok:
        print(f"  [OK] {r['name']}: {r['article_count']} articles")
    for r in tier1_fail:
        print(f"  [FAIL] {r['name']}: {r['status']} - {r['error']}")
    print()

    # Tier 2A
    print(f"TIER 2A (Think Tanks): {len(tier2a_ok)}/12 working")
    print("-" * 40)
    for r in tier2a_ok:
        print(f"  [OK] {r['name']}: {r['article_count']} articles")
    for r in tier2a_fail:
        print(f"  [FAIL] {r['name']}: {r['status']} - {r['error']}")
    print()

    # Tier 2B
    print(f"TIER 2B (Domain/Service): {len(tier2b_ok)}/10 working")
    print("-" * 40)
    for r in tier2b_ok:
        print(f"  [OK] {r['name']}: {r['article_count']} articles")
    for r in tier2b_fail:
        print(f"  [FAIL] {r['name']}: {r['status']} - {r['error']}")
    print()

    # Total
    total_ok = len(tier1_ok) + len(tier2a_ok) + len(tier2b_ok)
    total_fail = len(tier1_fail) + len(tier2a_fail) + len(tier2b_fail)
    print("=" * 70)
    print(f"TOTAL: {total_ok}/37 feeds working ({total_fail} failed)")
    print("=" * 70)

    # Save detailed results
    output = {
        "audit_date": datetime.now().isoformat(),
        "summary": {
            "total": 37,
            "working": total_ok,
            "failed": total_fail,
            "tier1": {"working": len(tier1_ok), "failed": len(tier1_fail)},
            "tier2a": {"working": len(tier2a_ok), "failed": len(tier2a_fail)},
            "tier2b": {"working": len(tier2b_ok), "failed": len(tier2b_fail)},
        },
        "results": results
    }

    with open("tier_feed_audit.json", "w") as f:
        json.dump(output, f, indent=2)

    print()
    print("Detailed results saved to: tier_feed_audit.json")

    # Return exit code based on results
    return 0 if total_fail == 0 else 1

if __name__ == "__main__":
    exit(asyncio.run(main()))
