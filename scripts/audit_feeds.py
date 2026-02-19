"""Audit all RSS feeds to check which are working."""
import asyncio
import httpx
import feedparser
import json
from datetime import datetime
from pathlib import Path

# All feeds from config
FEEDS = [
    {"id": "c4isrnet", "name": "C4ISRNET", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/?outputType=xml", "category": "News"},
    {"id": "c4isrnet-electronic-warfare", "name": "C4ISRNET Electronic Warfare", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/category/electronic-warfare/?outputType=xml", "category": "News"},
    {"id": "c4isrnet-cyber", "name": "C4ISRNET Cyber", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/category/cyber/?outputType=xml", "category": "News"},
    {"id": "c4isrnet-unmanned", "name": "C4ISRNET Unmanned", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/category/unmanned/?outputType=xml", "category": "News"},
    {"id": "c4isrnet-ai", "name": "C4ISRNET AI", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/category/artificial-intelligence/?outputType=xml", "category": "News"},
    {"id": "breaking-defense", "name": "Breaking Defense", "url": "https://breakingdefense.com/feed/", "category": "News"},
    {"id": "breaking-defense-full", "name": "Breaking Defense Full", "url": "https://breakingdefense.com/full-rss-feed/", "category": "News"},
    {"id": "defense-one", "name": "Defense One", "url": "https://www.defenseone.com/rss/all/", "category": "News"},
    {"id": "defense-one-technology", "name": "Defense One Technology", "url": "https://defenseone.com/rss/technology", "category": "News"},
    {"id": "defense-news", "name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", "category": "News"},
    {"id": "defense-news-naval", "name": "Defense News Naval", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/naval/?outputType=xml", "category": "News"},
    {"id": "defense-news-pentagon", "name": "Defense News Pentagon", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/pentagon/?outputType=xml", "category": "News"},
    {"id": "defense-news-congress", "name": "Defense News Congress", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/congress/?outputType=xml", "category": "News"},
    {"id": "defense-news-space", "name": "Defense News Space", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/space/?outputType=xml", "category": "News"},
    {"id": "defense-scoop", "name": "Defense Scoop", "url": "https://defensescoop.com/feed/", "category": "News"},
    {"id": "the-war-zone", "name": "The War Zone", "url": "https://twz.com/feed/", "category": "News"},
    {"id": "inside-defense", "name": "Inside Defense", "url": "https://insidedefense.com/rss", "category": "News"},
    {"id": "usni-news", "name": "USNI News", "url": "https://news.usni.org/feed", "category": "News"},
    {"id": "defense-daily", "name": "Defense Daily", "url": "https://www.defensedaily.com/feed/", "category": "News"},
    {"id": "spacenews", "name": "SpaceNews", "url": "https://spacenews.com/feed/", "category": "News"},
    {"id": "air-and-space-forces-magazine", "name": "Air and Space Forces Magazine", "url": "https://www.airandspaceforces.com/feed/", "category": "News"},
    {"id": "military-times", "name": "Military Times", "url": "https://www.militarytimes.com/arc/outboundfeeds/rss/?outputType=xml", "category": "News"},
    {"id": "army-times", "name": "Army Times", "url": "https://www.armytimes.com/arc/outboundfeeds/rss/?outputType=xml", "category": "News"},
    {"id": "navy-times", "name": "Navy Times", "url": "https://www.navytimes.com/arc/outboundfeeds/rss/?outputType=xml", "category": "News"},
    {"id": "air-force-times", "name": "Air Force Times", "url": "https://www.airforcetimes.com/arc/outboundfeeds/rss/?outputType=xml", "category": "News"},
    {"id": "marine-corps-times", "name": "Marine Corps Times", "url": "https://www.marinecorpstimes.com/arc/outboundfeeds/rss/?outputType=xml", "category": "News"},
    {"id": "govconwire", "name": "GovConWire", "url": "https://www.govconwire.com/feed/", "category": "News"},
    {"id": "executivegov", "name": "ExecutiveGov", "url": "https://executivegov.com/feed/", "category": "News"},
    {"id": "federal-news-network", "name": "Federal News Network", "url": "https://federalnewsnetwork.com/feed/", "category": "News"},
    {"id": "war-on-the-rocks", "name": "War on the Rocks", "url": "https://warontherocks.com/feed/", "category": "Analysis"},
    {"id": "war-on-the-rocks-podcasts", "name": "War on the Rocks Podcasts", "url": "https://warontherocks.com/feed/podcast/", "category": "Analysis"},
    {"id": "war-on-the-rocks-libsyn", "name": "War on the Rocks Libsyn", "url": "https://warontherocks.libsyn.com/rss", "category": "Podcast"},
    {"id": "modern-war-institute", "name": "Modern War Institute", "url": "https://mwi.westpoint.edu/feed/", "category": "Analysis"},
    {"id": "modern-war-institute-podcast", "name": "Modern War Institute Podcast", "url": "https://modern-war-institute.castos.com/feed", "category": "Podcast"},
    {"id": "small-wars-journal", "name": "Small Wars Journal", "url": "https://smallwarsjournal.com/index.php/rss.xml", "category": "Analysis"},
    {"id": "lawfare", "name": "Lawfare", "url": "https://www.lawfaremedia.org/feed", "category": "Analysis"},
    {"id": "the-cipher-brief", "name": "The Cipher Brief", "url": "https://www.thecipherbrief.com/feed", "category": "Analysis"},
    {"id": "foreign-affairs", "name": "Foreign Affairs", "url": "https://www.foreignaffairs.com/rss.xml", "category": "Analysis"},
    {"id": "foreign-policy", "name": "Foreign Policy", "url": "https://foreignpolicy.com/feed/", "category": "Analysis"},
    {"id": "the-diplomat", "name": "The Diplomat", "url": "https://thediplomat.com/feed/", "category": "Analysis"},
    {"id": "the-diplomat-asia-defense", "name": "The Diplomat Asia Defense", "url": "https://thediplomat.com/category/asia-defense/feed/", "category": "Analysis"},
    {"id": "rand-research", "name": "RAND Research", "url": "https://www.rand.org/pubs/new.xml", "category": "Think Tank"},
    {"id": "rand-commentary", "name": "RAND Commentary", "url": "https://www.rand.org/pubs/commentary.xml", "category": "Think Tank"},
    {"id": "rand-articles", "name": "RAND Articles", "url": "https://www.rand.org/pubs/articles.xml", "category": "Think Tank"},
    {"id": "rand-news-releases", "name": "RAND News Releases", "url": "https://www.rand.org/news/press.xml", "category": "Think Tank"},
    {"id": "rand-events", "name": "RAND Events", "url": "https://www.rand.org/events.xml", "category": "Think Tank"},
    {"id": "csis-audio", "name": "CSIS Audio", "url": "https://www.csis.org/files/media/feeds/csisaudio.xml", "category": "Think Tank"},
    {"id": "brookings", "name": "Brookings", "url": "https://www.brookings.edu/feed/", "category": "Think Tank"},
    {"id": "brookings-cafeteria-podcast", "name": "Brookings Cafeteria Podcast", "url": "http://brookingscafeteriapodcast.libsyn.com/rss", "category": "Podcast"},
    {"id": "heritage-foundation", "name": "Heritage Foundation", "url": "https://www.heritage.org/rss/all-research", "category": "Think Tank"},
    {"id": "daily-signal-heritage", "name": "Daily Signal (Heritage)", "url": "https://dailysignal.com/feed/", "category": "News"},
    {"id": "aei", "name": "AEI", "url": "https://www.aei.org/feed/", "category": "Think Tank"},
    {"id": "hudson-institute", "name": "Hudson Institute", "url": "https://www.hudson.org/feed", "category": "Think Tank"},
    {"id": "atlantic-council", "name": "Atlantic Council", "url": "https://www.atlanticcouncil.org/feed/", "category": "Think Tank"},
    {"id": "stimson-center", "name": "Stimson Center", "url": "https://www.stimson.org/feed/", "category": "Think Tank"},
    {"id": "carnegie-endowment", "name": "Carnegie Endowment", "url": "https://carnegieendowment.org/rss/solr/?fa=rss", "category": "Think Tank"},
    {"id": "cnas", "name": "CNAS", "url": "https://www.cnas.org/feed/", "category": "Think Tank"},
    {"id": "mitchell-institute", "name": "Mitchell Institute", "url": "https://mitchellaerospacepower.org/feed/", "category": "Think Tank"},
    {"id": "lexington-institute", "name": "Lexington Institute", "url": "https://www.lexingtoninstitute.org/feed/", "category": "Think Tank"},
    {"id": "fdd", "name": "FDD", "url": "https://www.fdd.org/feed/", "category": "Think Tank"},
    {"id": "long-war-journal", "name": "Long War Journal", "url": "https://feeds.feedburner.com/LongWarJournal", "category": "Operational"},
    {"id": "hoover-institution", "name": "Hoover Institution", "url": "https://www.hoover.org/rss", "category": "Think Tank"},
    {"id": "jamestown-foundation", "name": "Jamestown Foundation", "url": "https://jamestown.org/feed/", "category": "Think Tank"},
    {"id": "jamestown-china-brief", "name": "Jamestown China Brief", "url": "https://jamestown.org/programs/cb/feed/", "category": "Think Tank"},
    {"id": "jamestown-eurasia-daily-monitor", "name": "Jamestown Eurasia Daily Monitor", "url": "https://jamestown.org/programs/edm/feed/", "category": "Think Tank"},
    {"id": "national-bureau-of-asian-research", "name": "National Bureau of Asian Research", "url": "https://www.nbr.org/feed/", "category": "Think Tank"},
    {"id": "project-2049-institute", "name": "Project 2049 Institute", "url": "https://project2049.net/feed/", "category": "Think Tank"},
    {"id": "rusi-publications", "name": "RUSI Publications", "url": "https://www.rusi.org/rss/latest-publications.xml", "category": "Think Tank"},
    {"id": "rusi-commentary", "name": "RUSI Commentary", "url": "https://www.rusi.org/rss/latest-commentary.xml", "category": "Think Tank"},
    {"id": "rusi-events", "name": "RUSI Events", "url": "https://www.rusi.org/rss/upcoming-events.xml", "category": "Think Tank"},
    {"id": "rusi-whats-new", "name": "RUSI Whats New", "url": "https://www.rusi.org/rss/whats-new.xml", "category": "Think Tank"},
    {"id": "iiss", "name": "IISS", "url": "https://www.iiss.org/rss", "category": "Think Tank"},
    {"id": "ecfr", "name": "ECFR", "url": "https://ecfr.eu/feed/", "category": "Think Tank"},
    {"id": "chatham-house", "name": "Chatham House", "url": "https://www.chathamhouse.org/rss", "category": "Think Tank"},
    {"id": "aspi-the-strategist", "name": "ASPI The Strategist", "url": "https://www.aspistrategist.org.au/feed/", "category": "Think Tank"},
    {"id": "german-marshall-fund", "name": "German Marshall Fund", "url": "https://www.gmfus.org/feed", "category": "Think Tank"},
    {"id": "dod-news", "name": "DoD News", "url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?max=10&ContentType=1&Site=945", "category": "Government"},
    {"id": "army-news", "name": "Army News", "url": "https://www.army.mil/rss/", "category": "Government"},
    {"id": "navy-news", "name": "Navy News", "url": "https://www.navy.mil/Resources/Rss-Feeds/", "category": "Government"},
    {"id": "air-force-news", "name": "Air Force News", "url": "https://www.af.mil/RSS/", "category": "Government"},
    {"id": "marines-news", "name": "Marines News", "url": "https://www.marines.mil/RSS/", "category": "Government"},
    {"id": "space-force-news", "name": "Space Force News", "url": "https://www.spaceforce.mil/RSS/", "category": "Government"},
    {"id": "dsca-fms-notifications", "name": "DSCA FMS Notifications", "url": "https://www.dsca.mil/RSS", "category": "Government"},
    {"id": "gao-reports", "name": "GAO Reports", "url": "https://www.gao.gov/rss/reports.rss", "category": "Government"},
    {"id": "gao-defense", "name": "GAO Defense", "url": "https://www.gao.gov/rss/topic/defense.rss", "category": "Government"},
    {"id": "everycrsreport", "name": "EveryCRSReport", "url": "https://www.everycrsreport.com/rss.xml", "category": "Government"},
    {"id": "isw", "name": "ISW", "url": "https://www.iswresearch.org/feeds/posts/default", "category": "Operational"},
    {"id": "bellingcat", "name": "Bellingcat", "url": "https://www.bellingcat.com/feed/", "category": "Operational"},
    {"id": "bellingcat-podcast", "name": "Bellingcat Podcast", "url": "https://bellingcat.libsyn.com/rss", "category": "Podcast"},
    {"id": "oryx", "name": "Oryx", "url": "https://www.oryxspioenkop.com/feeds/posts/default?alt=rss", "category": "Operational"},
    {"id": "ieee-spectrum", "name": "IEEE Spectrum", "url": "https://spectrum.ieee.org/rss", "category": "Technology"},
    {"id": "ieee-spectrum-aerospace", "name": "IEEE Spectrum Aerospace", "url": "https://spectrum.ieee.org/rss/topic/aerospace", "category": "Technology"},
    {"id": "hackaday", "name": "Hackaday", "url": "https://hackaday.com/feed/", "category": "Technology"},
    {"id": "rtl-sdr-blog", "name": "RTL-SDR Blog", "url": "https://www.rtl-sdr.com/feed/", "category": "Technology"},
    {"id": "tectonic", "name": "Tectonic", "url": "https://tectonic.substack.com/feed", "category": "Technology"},
    {"id": "techcrunch", "name": "TechCrunch", "url": "https://techcrunch.com/feed/", "category": "Technology"},
    {"id": "wired-security", "name": "Wired Security", "url": "https://www.wired.com/feed/category/security/latest/rss", "category": "Technology"},
    {"id": "mit-technology-review", "name": "MIT Technology Review", "url": "https://www.technologyreview.com/feed/", "category": "Technology"},
    {"id": "real-clear-defense", "name": "Real Clear Defense", "url": "https://www.realcleardefense.com/index.xml", "category": "Analysis"},
    {"id": "naval-news", "name": "Naval News", "url": "https://navalnews.com/feed/", "category": "News"},
    {"id": "army-recognition", "name": "Army Recognition", "url": "https://armyrecognition.com/news", "category": "News"},
    {"id": "defence-blog", "name": "Defence Blog", "url": "https://defence-blog.com/feed/", "category": "News"},
    {"id": "the-atlantic", "name": "The Atlantic", "url": "https://www.theatlantic.com/feed/all/", "category": "News"},
    {"id": "the-atlantic-politics", "name": "The Atlantic Politics", "url": "https://theatlantic.com/feed/channel/politics/", "category": "News"},
    {"id": "defence-iq", "name": "Defence IQ", "url": "https://www.defenceiq.com/rss-feeds", "category": "News"},
    {"id": "spaceflight-now", "name": "Spaceflight Now", "url": "https://spaceflightnow.com/feed/", "category": "News"},
    {"id": "nasa-breaking-news", "name": "NASA Breaking News", "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss", "category": "Government"},
    {"id": "jpl-news", "name": "JPL News", "url": "https://www.jpl.nasa.gov/feeds/news", "category": "Government"},
    {"id": "esa-news", "name": "ESA News", "url": "https://esa.int/rssfeed/TopNews", "category": "Government"},
    {"id": "army-technology", "name": "Army Technology", "url": "https://www.army-technology.com/feed/", "category": "News"},
    {"id": "space-com", "name": "Space.com", "url": "https://www.space.com/feeds.xml", "category": "News"},
    {"id": "universe-today", "name": "Universe Today", "url": "https://www.universetoday.com/feed", "category": "News"},
    {"id": "propublica", "name": "ProPublica", "url": "https://propublica.org/feeds/propublica/main", "category": "News"},
    {"id": "ejil-talk", "name": "EJIL Talk", "url": "https://www.ejiltalk.org/feed/", "category": "Analysis"},
    {"id": "military-watch-magazine", "name": "Military Watch Magazine", "url": "https://militarywatchmagazine.com/feed/", "category": "News"},
    {"id": "defense-world", "name": "Defense World", "url": "https://defenseworld.net/feed/", "category": "News"},
    {"id": "quwa-defence", "name": "Quwa Defence", "url": "https://quwa.org/feed/", "category": "Analysis"},
    {"id": "bulgarian-military", "name": "Bulgarian Military", "url": "https://bulgarianmilitary.com/feed/", "category": "News"},
    {"id": "military-leak", "name": "Military Leak", "url": "https://militaryleak.com/feed/", "category": "News"},
    {"id": "task-and-purpose", "name": "Task and Purpose", "url": "https://taskandpurpose.com/feed/", "category": "News"},
    {"id": "duffel-blog", "name": "Duffel Blog", "url": "https://duffelblog.com/feed/", "category": "News"},
    {"id": "sofrep", "name": "SOFREP", "url": "https://sofrep.com/feed/", "category": "News"},
    {"id": "coffee-or-die-magazine", "name": "Coffee or Die Magazine", "url": "https://coffeeordie.com/feed/", "category": "News"},
    {"id": "dod-reads", "name": "DOD Reads", "url": "https://dodreads.com/feed/", "category": "News"},
    {"id": "national-guard", "name": "National Guard", "url": "https://www.nationalguard.mil/DesktopModules/ArticleCS/RSS.ashx", "category": "Government"},
    {"id": "strategic-studies-institute", "name": "Strategic Studies Institute", "url": "https://ssi.armywarcollege.edu/RSS/", "category": "Think Tank"},
    {"id": "cfr-blog", "name": "CFR Blog", "url": "https://www.cfr.org/blog", "category": "Think Tank"},
    {"id": "usafa-news", "name": "USAFA News", "url": "https://usafa.edu/feed/", "category": "Government"},
    {"id": "generation-jihad-podcast", "name": "Generation Jihad Podcast", "url": "https://feeds.redcircle.com/generation-jihad", "category": "Podcast"},
]


async def test_feed(client, feed):
    """Test a single feed and return results."""
    try:
        response = await client.get(feed["url"], follow_redirects=True)
        if response.status_code != 200:
            return {
                "id": feed["id"],
                "name": feed["name"],
                "url": feed["url"],
                "category": feed["category"],
                "status": "HTTP_ERROR",
                "http_code": response.status_code,
                "article_count": 0,
                "latest_title": "",
                "error": f"HTTP {response.status_code}"
            }

        parsed = feedparser.parse(response.text)
        article_count = len(parsed.entries)

        if article_count == 0:
            return {
                "id": feed["id"],
                "name": feed["name"],
                "url": feed["url"],
                "category": feed["category"],
                "status": "EMPTY",
                "http_code": 200,
                "article_count": 0,
                "latest_title": "",
                "error": "No articles found in feed"
            }

        return {
            "id": feed["id"],
            "name": feed["name"],
            "url": feed["url"],
            "category": feed["category"],
            "status": "OK",
            "http_code": 200,
            "article_count": article_count,
            "latest_title": parsed.entries[0].get("title", "")[:100] if parsed.entries else "",
            "error": None
        }
    except httpx.TimeoutException:
        return {
            "id": feed["id"],
            "name": feed["name"],
            "url": feed["url"],
            "category": feed["category"],
            "status": "TIMEOUT",
            "http_code": None,
            "article_count": 0,
            "latest_title": "",
            "error": "Request timed out"
        }
    except Exception as e:
        return {
            "id": feed["id"],
            "name": feed["name"],
            "url": feed["url"],
            "category": feed["category"],
            "status": "ERROR",
            "http_code": None,
            "article_count": 0,
            "latest_title": "",
            "error": str(e)[:150]
        }


async def main():
    """Run the audit."""
    results = []

    async with httpx.AsyncClient(
        timeout=15.0,
        headers={"User-Agent": "Mozilla/5.0 (compatible; RSS-Audit/1.0)"}
    ) as client:
        # Process in batches of 10 for efficiency
        total = len(FEEDS)
        for i in range(0, total, 10):
            batch = FEEDS[i:i+10]
            batch_results = await asyncio.gather(*[test_feed(client, f) for f in batch])
            results.extend(batch_results)
            print(f"  Processed {min(i+10, total)}/{total} feeds...")

    return results


if __name__ == "__main__":
    print(f"=" * 60)
    print(f"RSS FEED AUDIT")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Total feeds to test: {len(FEEDS)}")
    print(f"=" * 60)
    print()

    results = asyncio.run(main())

    # Categorize results
    ok_feeds = [r for r in results if r["status"] == "OK"]
    empty_feeds = [r for r in results if r["status"] == "EMPTY"]
    http_error_feeds = [r for r in results if r["status"] == "HTTP_ERROR"]
    timeout_feeds = [r for r in results if r["status"] == "TIMEOUT"]
    error_feeds = [r for r in results if r["status"] == "ERROR"]

    # Print summary
    print()
    print(f"=" * 60)
    print("SUMMARY")
    print(f"=" * 60)
    print(f"  OK:         {len(ok_feeds):3d} feeds working")
    print(f"  EMPTY:      {len(empty_feeds):3d} feeds returned no articles")
    print(f"  HTTP_ERROR: {len(http_error_feeds):3d} feeds returned HTTP errors")
    print(f"  TIMEOUT:    {len(timeout_feeds):3d} feeds timed out")
    print(f"  ERROR:      {len(error_feeds):3d} feeds had other errors")
    print()

    # Print working feeds
    if ok_feeds:
        print(f"=" * 60)
        print("WORKING FEEDS")
        print(f"=" * 60)
        for r in sorted(ok_feeds, key=lambda x: -x["article_count"]):
            print(f"  [{r['category']:12s}] {r['name']:40s} ({r['article_count']} articles)")

    # Print problematic feeds
    if empty_feeds or http_error_feeds or timeout_feeds or error_feeds:
        print()
        print(f"=" * 60)
        print("PROBLEMATIC FEEDS")
        print(f"=" * 60)

        for r in empty_feeds:
            print(f"  [EMPTY]      {r['name']:40s} - {r['url']}")

        for r in http_error_feeds:
            print(f"  [HTTP {r['http_code']}]   {r['name']:40s} - {r['error']}")

        for r in timeout_feeds:
            print(f"  [TIMEOUT]    {r['name']:40s} - {r['url']}")

        for r in error_feeds:
            print(f"  [ERROR]      {r['name']:40s} - {r['error'][:60]}")

    # Save to JSON
    output_path = Path(__file__).parent.parent / "rss_feed_audit.json"
    audit_data = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": len(results),
            "ok": len(ok_feeds),
            "empty": len(empty_feeds),
            "http_error": len(http_error_feeds),
            "timeout": len(timeout_feeds),
            "error": len(error_feeds),
        },
        "working_feeds": ok_feeds,
        "problematic_feeds": empty_feeds + http_error_feeds + timeout_feeds + error_feeds,
    }

    with open(output_path, "w") as f:
        json.dump(audit_data, f, indent=2)

    print()
    print(f"Full audit saved to: {output_path}")
