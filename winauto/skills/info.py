"""Quick facts from free services (no API keys): currency, dictionary, Wikipedia, news."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from winauto.adapters.http import FetchError, fetch, fetch_json, strip_tags
from winauto.core.context import Context
from winauto.core.skill import QuickRule, Skill, ToolResult, fail, ok, tool
from winauto.skills.shared.units import known_unit

CURRENCY_WORDS = {
    "dollar": "USD", "dollars": "USD", "usd": "USD", "bucks": "USD", "euro": "EUR", "euros": "EUR",
    "pound": "GBP", "pounds": "GBP", "quid": "GBP", "yen": "JPY", "yuan": "CNY", "rmb": "CNY",
    "dirham": "AED", "dirhams": "AED", "riyal": "SAR", "riyals": "SAR", "ringgit": "MYR", "won": "KRW",
    "franc": "CHF", "francs": "CHF", "baht": "THB", "taka": "BDT", "bitcoin": "BTC",
}
RUPEE_BY_COUNTRY = {"977": "NPR", "92": "PKR", "94": "LKR", "91": "INR"}


class InfoSkill(Skill):
    name = "info"
    icon = "book"
    description = "Currency rates, word definitions, Wikipedia summaries, news headlines."
    keywords = r"\b(currency|exchange rate|convert|usd|eur|npr|inr|rupees?|dollars?|euros?|define|definition|meaning|wiki(?:pedia)?|news|headlines)\b"
    prompt_hint = "Info: use convert_currency for money (live rates), get_news for headlines."

    def __init__(self, ctx: Context, json_fetcher: Callable[..., Any] | None = None,
                 fetcher: Callable[..., tuple[str, str]] | None = None):
        super().__init__(ctx)
        self._json = json_fetcher or fetch_json
        self._fetch = fetcher or fetch

    # ----- currency -----

    def _code(self, name: str) -> str:
        n = name.strip().lower().rstrip(".")
        if n in ("rupee", "rupees", "rs", "rs."):
            return RUPEE_BY_COUNTRY.get(self.ctx.config.messaging.default_country_code.strip("+"), "INR")
        return CURRENCY_WORDS.get(n, n.upper())

    def _rates(self, base: str) -> dict[str, float]:
        key = f"fx:{base}"
        cached = self.ctx.db.get_value(key)
        if cached:
            stamp, rates = json.loads(cached)
            if time.time() - stamp < 6 * 3600:
                return rates
        data = self._json(f"https://open.er-api.com/v6/latest/{urllib.parse.quote(base)}", timeout=10)
        if data.get("result") != "success":
            raise FetchError(f"No exchange rates for {base}")
        rates = data["rates"]
        self.ctx.db.set_value(key, json.dumps([time.time(), rates]))
        return rates

    @tool("Convert money between currencies with today's rates.",
          params={"amount": "How much", "from_currency": "e.g. USD, euros, rupees", "to_currency": "e.g. NPR, INR"})
    def convert_currency(self, amount: float, from_currency: str, to_currency: str) -> ToolResult:
        src, dst = self._code(from_currency), self._code(to_currency)
        try:
            rates = self._rates(src)
        except (FetchError, KeyError, ValueError) as exc:
            return fail(f"Couldn't get exchange rates: {exc}")
        if dst not in rates:
            return fail(f"I don't have a rate for {dst}.")
        value = amount * rates[dst]
        return ok(f"{amount:,.2f} {src} = **{value:,.2f} {dst}** (1 {src} = {rates[dst]:,.4f} {dst})",
                  data={"value": round(value, 2)})

    # ----- dictionary -----

    @tool("Define an English word.", params={"word": "The word"})
    def define_word(self, word: str) -> ToolResult:
        w = word.strip().lower()
        try:
            data = self._json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(w)}", timeout=10)
        except FetchError:
            return fail(f"I couldn't find “{word}” in the dictionary.")
        if not isinstance(data, list) or not data:
            return fail(f"I couldn't find “{word}” in the dictionary.")
        entry = data[0]
        phonetic = entry.get("phonetic") or next((p.get("text") for p in entry.get("phonetics", []) if p.get("text")), "")
        lines = [f"**{entry.get('word', w)}** {phonetic}".strip()]
        for meaning in entry.get("meanings", [])[:3]:
            defs = meaning.get("definitions", [])[:2]
            for i, d in enumerate(defs, 1):
                example = f" — *“{d['example']}”*" if d.get("example") else ""
                lines.append(f"- *{meaning.get('partOfSpeech', '')}* {d.get('definition', '')}{example}")
        return ok("\n".join(lines))

    # ----- wikipedia -----

    @tool("Get a short Wikipedia summary of a topic.", params={"topic": "Person, place, thing or idea"}, final=False)
    def wikipedia_summary(self, topic: str) -> ToolResult:
        q = urllib.parse.quote(topic.strip())
        try:
            found = self._json(f"https://en.wikipedia.org/w/api.php?action=opensearch&limit=1&format=json&search={q}", timeout=10)
            title = found[1][0] if isinstance(found, list) and len(found) > 1 and found[1] else None
            if not title:
                return fail(f"Wikipedia has nothing on “{topic}”.")
            page = self._json("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_")), timeout=10)
        except (FetchError, IndexError, TypeError) as exc:
            return fail(f"Couldn't reach Wikipedia: {exc}")
        extract = page.get("extract", "").strip()
        url = page.get("content_urls", {}).get("desktop", {}).get("page", "")
        if not extract:
            return fail(f"Wikipedia has nothing on “{topic}”.")
        return ok(f"**{page.get('title', title)}**: {extract}" + (f"\n[Wikipedia]({url})" if url else ""),
                  data={"title": page.get("title"), "summary": extract, "url": url})

    # ----- news -----

    @tool("Latest news headlines, optionally about a topic.", params={"topic": "Optional topic", "count": "How many (default 6)"})
    def get_news(self, topic: str = "", count: int = 6) -> ToolResult:
        base = "https://news.google.com/rss"
        url = f"{base}/search?q={urllib.parse.quote(topic)}&hl=en-US&gl=US&ceid=US:en" if topic.strip() else f"{base}?hl=en-US&gl=US&ceid=US:en"
        try:
            xml, _ = self._fetch(url, timeout=10)
            items = parse_rss(xml)[: max(1, min(count, 15))]
        except (FetchError, ET.ParseError) as exc:
            return fail(f"Couldn't get the news: {exc}")
        if not items:
            return ok(f"No news found{' about ' + topic if topic else ''}.")
        lines = [f"- [{it['title']}]({it['link']})" + (f" · {it['source']}" if it["source"] else "") + (f" · {it['when']}" if it["when"] else "")
                 for it in items]
        heading = f"News about {topic}" if topic.strip() else "Top headlines"
        return ok(f"{heading}:\n" + "\n".join(lines), data={"headlines": [i["title"] for i in items]})

    def quick_rules(self) -> list[QuickRule]:
        money = r"(?P<f>[a-z]{3}|dollars?|euros?|pounds?|yen|yuan|rupees?|rs\.?|dirhams?|riyals?|bucks|bitcoin)"
        money_to = money.replace("?P<f>", "?P<t>")

        def currency(m):
            src, dst = self._code(m["f"]), self._code(m["t"])
            if not (re.fullmatch(r"[A-Z]{3}", src) and re.fullmatch(r"[A-Z]{3}", dst)):
                return None
            if known_unit(m["f"]) or known_unit(m["t"]):
                return None  # it's a unit conversion (e.g. "kms")
            return "convert_currency", {"amount": float(m["a"].replace(",", "")), "from_currency": src, "to_currency": dst}

        return [
            QuickRule(rf"(?:convert\s+|how\s+much\s+is\s+)?(?P<a>[\d.,]+)\s*{money}\s+(?:to|in|into)\s+{money_to}", currency, priority=34),
            QuickRule(r"(?:define|definition\s+of|meaning\s+of|what\s+does\s+(?:the\s+word\s+)?)\s*(?P<w>[a-z-]+)(?:\s+mean)?",
                      lambda m: ("define_word", {"word": m["w"]})),
            QuickRule(r"(?:wiki|wikipedia)\s+(?P<t>.+)", lambda m: ("wikipedia_summary", {"topic": m["t"]})),
            QuickRule(r"(?:show\s+(?:me\s+)?)?(?:the\s+)?(?:latest\s+|top\s+|today's\s+)?(?:news|headlines)(?:\s+(?:about|on|for)\s+(?P<t>.+))?",
                      lambda m: ("get_news", {"topic": m["t"] or ""})),
        ]


def parse_rss(xml: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml)
    items = []
    for item in root.iter("item"):
        title = strip_tags(item.findtext("title") or "")
        source = item.findtext("source") or ""
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        when = ""
        if item.findtext("pubDate"):
            try:
                dt = parsedate_to_datetime(item.findtext("pubDate"))
                hours = max(0, int((time.time() - dt.timestamp()) // 3600))
                when = f"{hours} h ago" if hours < 24 else f"{hours // 24} d ago"
            except (TypeError, ValueError):
                pass
        items.append({"title": title, "link": item.findtext("link") or "", "source": source, "when": when})
    return items
