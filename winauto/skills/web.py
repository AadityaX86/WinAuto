"""Websites, web searches, reading pages, and weather."""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any, Callable

from winauto.core.matching import normalize
from winauto.core.quick import is_simple
from winauto.core.skill import QuickRule, Skill, Suggestion, ToolResult, fail, ok, tool
from winauto.adapters.http import FetchError, fetch, fetch_json, html_to_text, strip_tags
from winauto.adapters.winos.shell import open_url

log = logging.getLogger(__name__)

SITES = {
    "youtube": "https://www.youtube.com", "yt": "https://www.youtube.com",
    "gmail": "https://mail.google.com", "google mail": "https://mail.google.com",
    "google": "https://www.google.com", "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com", "google docs": "https://docs.google.com",
    "google sheets": "https://sheets.google.com", "google calendar": "https://calendar.google.com",
    "google maps": "https://maps.google.com", "maps": "https://maps.google.com",
    "google photos": "https://photos.google.com", "google translate": "https://translate.google.com",
    "translate": "https://translate.google.com", "google news": "https://news.google.com",
    "github": "https://github.com", "gitlab": "https://gitlab.com", "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com", "facebook": "https://www.facebook.com",
    "fb": "https://www.facebook.com", "messenger": "https://www.messenger.com",
    "instagram": "https://www.instagram.com", "insta": "https://www.instagram.com",
    "twitter": "https://x.com", "x": "https://x.com", "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com", "netflix": "https://www.netflix.com",
    "prime video": "https://www.primevideo.com", "amazon": "https://www.amazon.com",
    "wikipedia": "https://en.wikipedia.org", "wiki": "https://en.wikipedia.org",
    "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    "whatsapp": "https://web.whatsapp.com", "whatsapp web": "https://web.whatsapp.com",
    "outlook": "https://outlook.live.com", "hotmail": "https://outlook.live.com",
    "twitch": "https://www.twitch.tv", "pinterest": "https://www.pinterest.com", "tiktok": "https://www.tiktok.com",
    "spotify": "https://open.spotify.com", "discord": "https://discord.com/app",
    "telegram": "https://web.telegram.org", "notion": "https://www.notion.so", "figma": "https://www.figma.com",
    "canva": "https://www.canva.com", "quora": "https://www.quora.com", "medium": "https://medium.com",
    "daraz": "https://www.daraz.com.np", "flipkart": "https://www.flipkart.com",
}

SITE_SEARCH = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "amazon": "https://www.amazon.com/s?k={q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "github": "https://github.com/search?q={q}",
    "reddit": "https://www.reddit.com/search/?q={q}",
    "maps": "https://www.google.com/maps/search/{q}",
    "images": "https://www.google.com/search?tbm=isch&q={q}",
    "news": "https://news.google.com/search?q={q}",
    "stackoverflow": "https://stackoverflow.com/search?q={q}",
    "spotify": "https://open.spotify.com/search/{q}",
    "translate": "https://translate.google.com/?sl=auto&tl=en&text={q}",
    "twitter": "https://x.com/search?q={q}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={q}",
}
SITE_SEARCH_ALIASES = {"yt": "youtube", "google maps": "maps", "map": "maps", "wiki": "wikipedia",
                       "x": "twitter", "pictures": "images", "photos": "images", "stack overflow": "stackoverflow"}

ENGINES = {
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
}

_FILE_EXT = r"(?:exe|bat|cmd|lnk|msi|txt|pdf|docx?|xlsx?|pptx?|png|jpe?g|gif|mp3|mp4|mkv|zip|rar|py|json|csv)"
URL_RE = re.compile(rf"^(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.(?!{_FILE_EXT}\b)[a-z]{{2,}}(?::\d+)?(?:[/?#]\S*)?$", re.I)


def looks_like_url(text: str) -> bool:
    return bool(URL_RE.match(text.strip())) and " " not in text.strip()


def parse_ddg(html: str, limit: int = 6) -> list[dict[str, str]]:
    """Results from DuckDuckGo's HTML page (html.duckduckgo.com or lite)."""
    results: list[dict[str, str]] = []
    links = re.findall(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
    snippets = re.findall(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div|td)>', html, re.S)
    if not links:  # lite layout
        links = re.findall(r"<a[^>]+href=\"([^\"]+)\"[^>]*class=['\"]result-link['\"][^>]*>(.*?)</a>", html, re.S)
        links += re.findall(r"<a[^>]+class=['\"]result-link['\"][^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", html, re.S)
        snippets = re.findall(r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>", html, re.S)
    for i, (href, title) in enumerate(links):
        url = _unwrap_ddg(href)
        if not url or "duckduckgo.com/y.js" in href or "/y.js?" in url:
            continue  # ads
        results.append({
            "title": strip_tags(title),
            "url": url,
            "snippet": strip_tags(snippets[i]) if i < len(snippets) else "",
        })
        if len(results) >= limit:
            break
    return results


def _unwrap_ddg(href: str) -> str:
    href = href.replace("&amp;", "&")
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        return target
    return href


class WebSkill(Skill):
    name = "web"
    description = "Open websites, search the web, read pages, weather."
    keywords = r"\b(website|site|search|google|browser|url|link|youtube|weather|rain|news|web|online|look up)\b|\.\w{2,}\b"
    always = True
    prompt_hint = (
        "Web: for facts or anything current, call search_web (results come back to you) and answer "
        "from them with the source name. Call read_webpage on a result if snippets aren't enough. "
        "Use open_website only when the user wants a site opened in the browser."
    )

    def __init__(self, ctx: Any, opener: Callable[[str], Any] | None = None,
                 fetcher: Callable[..., tuple[str, str]] | None = None,
                 json_fetcher: Callable[..., Any] | None = None):
        super().__init__(ctx)
        self._open = opener or open_url
        self._fetch = fetcher or fetch
        self._fetch_json = json_fetcher or fetch_json

    # ----- helpers -----

    def _sites(self) -> dict[str, str]:
        sites = dict(SITES)
        sites.update({normalize(k): v for k, v in self.ctx.config.extra_sites.items()})
        return sites

    def site_url(self, name: str) -> str | None:
        key = normalize(re.sub(r"\s+(?:website|site|web ?site|dot com|\.com|homepage)$", "", name.strip(), flags=re.I))
        key = re.sub(r"^(?:the|my)\s+", "", key)
        return self._sites().get(key)

    def _engine_url(self, query: str) -> str:
        template = ENGINES.get(self.ctx.config.search_engine, ENGINES["google"])
        return template.format(q=urllib.parse.quote_plus(query))

    def search(self, query: str, limit: int = 6) -> list[dict[str, str]]:
        q = urllib.parse.quote_plus(query)
        errors = []
        for url in (f"https://html.duckduckgo.com/html/?q={q}", f"https://lite.duckduckgo.com/lite/?q={q}"):
            try:
                html, _ = self._fetch(url, timeout=10)
            except FetchError as exc:
                errors.append(str(exc))
                continue
            results = parse_ddg(html, limit)
            if results:
                return results
        if errors:
            raise FetchError(errors[-1])
        return []

    # ----- tools -----

    @tool(
        "Open a website in the browser.",
        params={"site": "A site name (e.g. 'youtube', 'gmail') or a web address"},
        hides_popup=True,
    )
    def open_website(self, site: str) -> ToolResult:
        site = site.strip()
        url = self.site_url(site)
        label = site[:1].upper() + site[1:] if url else site
        if url is None and looks_like_url(site):
            url = site if re.match(r"^https?://", site, re.I) else "https://" + site
        if url is None:
            # Unknown name: DuckDuckGo's "I'm feeling lucky" goes to the top result.
            url = "https://duckduckgo.com/?q=" + urllib.parse.quote_plus("\\" + site)
            label = f"the top result for '{site}'"
        self._open(url)
        return ok(f"Opened {label}.", data={"url": url})

    @tool(
        "Search the web. By default the results come back to you so you can answer the question. "
        "Set open_in_browser=true only if the user wants to see the search page.",
        params={"query": "What to search for", "open_in_browser": "Show the results in the browser instead"},
        final=False,
    )
    def search_web(self, query: str, open_in_browser: bool = False) -> ToolResult:
        if open_in_browser:
            self._open(self._engine_url(query))
            engine = self.ctx.config.search_engine.capitalize()
            return ok(f"Searching {engine} for “{query}”.")
        try:
            results = self.search(query)
        except FetchError as exc:
            self._open(self._engine_url(query))
            return ok(f"I couldn't fetch results ({exc}), so I opened the search in your browser.")
        if not results:
            return ok(f"No results for “{query}”.", data={"results": []})
        lines = [f"{i}. {r['title']} — {r['snippet']} ({r['url']})" for i, r in enumerate(results, 1)]
        return ok("Search results:\n" + "\n".join(lines), data={"results": results})

    @tool(
        "Search inside a specific site (youtube, amazon, wikipedia, github, reddit, maps, images, news, spotify...) in the browser.",
        params={"site": "Which site", "query": "What to search for"},
        hides_popup=True,
    )
    def search_site(self, site: str, query: str) -> ToolResult:
        key = normalize(site)
        key = SITE_SEARCH_ALIASES.get(key, key)
        template = SITE_SEARCH.get(key)
        if not template:
            # Fall back to a normal search limited to that site.
            domain = self.site_url(site)
            q = f"site:{urllib.parse.urlparse(domain).netloc} {query}" if domain else f"{site} {query}"
            self._open(self._engine_url(q))
            return ok(f"Searching {site} for “{query}”.")
        # maps/spotify put the query in the path, the rest in ?q=
        quoted = urllib.parse.quote(query) if key in ("maps", "spotify") else urllib.parse.quote_plus(query)
        self._open(template.format(q=quoted))
        return ok(f"Searching {key.capitalize()} for “{query}”.")

    @tool(
        "Read the text of a web page so you can answer from it.",
        params={"url": "The page address"},
        final=False,
    )
    def read_webpage(self, url: str) -> ToolResult:
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        try:
            html, final_url = self._fetch(url, timeout=15)
        except FetchError as exc:
            return fail(str(exc))
        text, title = html_to_text(html)
        if not text:
            return fail("That page had no readable text (it may need JavaScript).")
        clipped = text[:5000]
        return ok(f"Read “{title or final_url}”.", data={"title": title, "url": final_url, "text": clipped})

    @tool(
        "Current weather and forecast.",
        params={"location": "City or place. Leave empty for the user's saved or current location."},
    )
    def get_weather(self, location: str = "") -> ToolResult:
        place = location.strip() or self.ctx.config.weather_location
        url = "https://wttr.in/" + urllib.parse.quote(place) + "?format=j1"
        try:
            data = self._fetch_json(url, timeout=12)
        except FetchError as exc:
            return fail(f"Couldn't get the weather: {exc}")
        try:
            return ok(format_weather(data, place), data={"source": "wttr.in"})
        except (KeyError, IndexError, TypeError, ValueError):
            return fail(f"I couldn't find weather for '{place}'.")

    # ----- launcher -----

    def suggest(self, query: str) -> list[Suggestion]:
        q = query.strip()
        if not q:
            return []
        out = []
        if looks_like_url(q):
            out.append(Suggestion(title=f"Open {q}", subtitle="Website", tool="open_website", args={"site": q},
                                  kind="Website", icon="globe", score=95))
        key = normalize(re.sub(r"^(?:open|go to|visit)\s+", "", q, flags=re.I))
        if len(key) >= 2:
            for name, url in self._sites().items():
                if name.startswith(key) and len(name) <= len(key) + 12:
                    out.append(Suggestion(title=f"Open {name.title()}", subtitle=url, tool="open_website",
                                          args={"site": name}, kind="Website", icon="globe",
                                          score=90 if name == key else 76))
        if len(q) >= 2:
            engine = self.ctx.config.search_engine.capitalize()
            out.append(Suggestion(title=f"Search {engine} for “{q}”", subtitle="Opens your browser", tool="search_web",
                                  args={"query": q, "open_in_browser": True}, kind="Web", icon="search", score=15))
        return out[:5]

    # ----- quick commands -----

    def quick_rules(self) -> list[QuickRule]:
        def open_url(m):
            t = m["t"].strip()
            return ("open_website", {"site": t}) if looks_like_url(t) else None

        def open_site(m):
            t = m["t"].strip()
            return ("open_website", {"site": t}) if is_simple(t) and self.site_url(t) else None

        def site_search(m):
            site, q = m["site"], m["q"]
            key = SITE_SEARCH_ALIASES.get(normalize(site), normalize(site))
            return ("search_site", {"site": key, "query": q}) if key in SITE_SEARCH else None

        def weather(m):
            loc = (m["loc"] or "").strip()
            return "get_weather", ({"location": loc} if loc else {})

        sites = "|".join(sorted({*SITE_SEARCH, *SITE_SEARCH_ALIASES}, key=len, reverse=True))
        return [
            QuickRule(r"(?:open|go to|visit|browse to|navigate to|launch)\s+(?P<t>\S+)", open_url, priority=30),
            QuickRule(r"(?:open|go to|visit|launch|show me)\s+(?P<t>.+)", open_site, priority=50),
            QuickRule(r"(?:play|watch|find)\s+(?P<q>.+?)\s+on\s+(?P<site>youtube|yt|spotify)", site_search, priority=45),
            QuickRule(rf"(?:search|look up|find)\s+(?P<site>{sites})\s+(?:for\s+)?(?P<q>.+)", site_search, priority=45),
            QuickRule(rf"(?:search|look up|look for|find)\s+(?:for\s+)?(?P<q>.+?)\s+on\s+(?P<site>{sites})", site_search, priority=45),
            QuickRule(r"(?P<site>youtube|yt)\s+(?P<q>.+)", site_search, priority=45),
            QuickRule(r"(?:directions\s+to|where\s+is|show\s+me)\s+(?P<q>.+?)\s+on\s+(?P<site>maps|google maps|map)", site_search, priority=45),
            QuickRule(r"(?:search|google|bing|look up|lookup)\s+(?:for\s+|up\s+)?(?P<q>.+)",
                      lambda m: None if re.match(r"(?:in\s+|through\s+)?(?:my|the)\s+(?:e-?mails?|inbox|gmail|notes?|files?|"
                                                 r"downloads?|documents?|computer|pc|contacts?|todos?|tasks?)\b", m["q"], re.I)
                      else ("search_web", {"query": m["q"], "open_in_browser": True}), priority=70),
            QuickRule(r"(?:(?:what'?s|what is|how'?s|how is)\s+)?(?:the\s+)?weather(?:\s+like)?(?:\s+(?:in|at|for)\s+(?P<loc>.+?))?"
                      r"(?:\s+(?:today|now|right now|tomorrow|this week))?", weather),
            QuickRule(r"(?:is it|will it|is it going to)\s+(?:be\s+)?(?:rain|raining|snow|snowing|hot|cold|sunny)"
                      r"(?:\s+(?:today|tomorrow|now))?(?:\s+in\s+(?P<loc>.+?))?(?:\s+(?:today|tomorrow))?", weather),
        ]


def format_weather(data: dict, place: str) -> str:
    cur = data["current_condition"][0]
    area = data.get("nearest_area", [{}])[0]
    name = place or ", ".join(
        v for v in (area.get("areaName", [{}])[0].get("value"), area.get("country", [{}])[0].get("value")) if v
    ) or "Your area"
    desc = cur["weatherDesc"][0]["value"].strip().lower()
    line1 = f"**{name.title() if place else name}**: {cur['temp_C']}°C and {desc} (feels like {cur['FeelsLikeC']}°C), humidity {cur['humidity']}%."
    days = data.get("weather", [])
    parts = [line1]
    for label, day in zip(("Today", "Tomorrow"), days[:2]):
        rain = max((int(h.get("chanceofrain", 0)) for h in day.get("hourly") or []), default=0)
        hourly = day.get("hourly") or []
        mid = hourly[len(hourly) // 2] if hourly else {}  # around midday
        sky = mid.get("weatherDesc", [{"value": ""}])[0]["value"].strip().lower()
        sky_text = f", {sky}" if sky else ""
        parts.append(f"{label}: {day['mintempC']}–{day['maxtempC']}°C{sky_text}, {rain}% chance of rain.")
    return "\n".join(parts)
