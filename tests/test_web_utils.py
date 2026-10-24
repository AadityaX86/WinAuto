from __future__ import annotations

import pytest

from winauto.core.quick import QuickMatcher
from winauto.core.registry import Registry
from winauto.net import FetchError, html_to_text
from winauto.skills.apps import AppsSkill
from winauto.skills.notes import NotesSkill
from winauto.skills.utils import UtilsSkill, calculate_expression, convert, format_number
from winauto.skills.web import WebSkill, looks_like_url, parse_ddg

DDG_HTML = """
<div class="result results_links results_links_deep result--ad">
 <h2 class="result__title"><a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad_domain=x">Buy now</a></h2>
 <a class="result__snippet" href="#">An ad</a></div>
<div class="result results_links results_links_deep web-result ">
 <h2 class="result__title"><a rel="nofollow" class="result__a"
   href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2F&amp;rut=abc">Welcome to <b>Python</b>.org</a></h2>
 <a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">The official home of the <b>Python</b> Programming Language</a>
</div>
<div class="result results_links results_links_deep web-result ">
 <h2 class="result__title"><a rel="nofollow" class="result__a" href="https://docs.python.org/3/">Python 3 docs</a></h2>
 <a class="result__snippet" href="#">Documentation &amp; tutorials</a>
</div>
"""

WTTR = {
    "current_condition": [{"temp_C": "18", "FeelsLikeC": "17", "humidity": "60",
                           "weatherDesc": [{"value": "Partly cloudy "}]}],
    "nearest_area": [{"areaName": [{"value": "Kathmandu"}], "country": [{"value": "Nepal"}]}],
    "weather": [
        {"mintempC": "12", "maxtempC": "22", "hourly": [{"chanceofrain": "10", "weatherDesc": [{"value": "Sunny"}]}] * 8},
        {"mintempC": "11", "maxtempC": "23", "hourly": [{"chanceofrain": "70", "weatherDesc": [{"value": "Light rain"}]}] * 8},
    ],
}


class Browser:
    def __init__(self):
        self.opened = []

    def __call__(self, url):
        self.opened.append(url)
        return True


@pytest.fixture
def web(ctx):
    browser = Browser()
    pages = {}

    def fetcher(url, **kw):
        for key, value in pages.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value, url
        raise FetchError("offline")

    skill = WebSkill(ctx, opener=browser, fetcher=fetcher, json_fetcher=lambda url, **kw: WTTR)
    return skill, browser, pages


def test_parse_ddg_skips_ads_and_unwraps():
    results = parse_ddg(DDG_HTML)
    assert [r["url"] for r in results] == ["https://www.python.org/", "https://docs.python.org/3/"]
    assert results[0]["title"] == "Welcome to Python.org"
    assert results[1]["snippet"] == "Documentation & tutorials"


def test_search_web_returns_results_for_model(web):
    skill, browser, pages = web
    pages["html.duckduckgo.com"] = DDG_HTML
    r = skill.search_web("python")
    assert r.ok and len(r.data["results"]) == 2 and browser.opened == []


def test_search_web_falls_back_to_browser(web):
    skill, browser, pages = web
    r = skill.search_web("python")  # fetcher is "offline"
    assert r.ok and "opened the search" in r.message
    assert browser.opened == ["https://www.google.com/search?q=python"]


def test_open_website(web):
    skill, browser, _ = web
    assert skill.open_website("YouTube").ok
    assert skill.open_website("example.org/page").ok
    assert skill.open_website("the bbc website").ok
    assert browser.opened[:2] == ["https://www.youtube.com", "https://example.org/page"]
    assert browser.opened[2].startswith("https://duckduckgo.com/?q=%5C")


def test_search_site(web):
    skill, browser, _ = web
    skill.search_site("yt", "lofi beats")
    skill.search_site("maps", "coffee near me")
    skill.search_site("imdb", "dune")
    assert browser.opened[0] == "https://www.youtube.com/results?search_query=lofi+beats"
    assert browser.opened[1] == "https://www.google.com/maps/search/coffee%20near%20me"
    assert "dune" in browser.opened[2]


def test_read_webpage(web):
    skill, _, pages = web
    pages["example.com"] = "<html><head><title>Ex</title><script>x=1</script></head><body><nav>menu</nav><p>Hello world text.</p></body></html>"
    r = skill.read_webpage("example.com")
    assert r.ok and r.data["title"] == "Ex" and r.data["text"] == "Hello world text."


def test_weather_format(web):
    skill, _, _ = web
    r = skill.get_weather("kathmandu")
    assert r.ok
    assert "**Kathmandu**: 18°C and partly cloudy (feels like 17°C)" in r.message
    assert "Tomorrow: 11–23°C, light rain, 70% chance of rain." in r.message


def test_html_to_text():
    text, title = html_to_text("<title>T &amp; U</title><div>One</div><style>p{}</style><p>Two</p>")
    assert title == "T & U" and text == "One\nTwo"


@pytest.mark.parametrize("text, ok_", [("google.com", True), ("https://x.com/a?b=1", True), ("notepad.exe", False),
                                        ("report.pdf", False), ("hello", False), ("my site.com", False)])
def test_looks_like_url(text, ok_):
    assert looks_like_url(text) is ok_


# ---------- utils ----------

@pytest.mark.parametrize("expr, value", [
    ("2+2", 4), ("15% of 2400", 360), ("(12 + 8) * 3", 60), ("2^10", 1024), ("1,000 * 3", 3000),
    ("sqrt(144)", 12), ("200 + 10%", 220), ("10 divided by 4", 2.5), ("7 x 6", 42), ("5 squared", 25),
])
def test_calculator(expr, value):
    assert calculate_expression(expr) == pytest.approx(value)


def test_calculator_rejects_code():
    for bad in ("__import__('os')", "open('x')", "9**99999"):
        with pytest.raises((ValueError, SyntaxError)):
            calculate_expression(bad)


def test_conversions():
    assert convert(10, "km", "miles")[0] == pytest.approx(6.2137, rel=1e-3)
    assert convert(100, "F", "C")[0] == pytest.approx(37.7778, rel=1e-4)
    assert convert(5, "lbs", "kg")[0] == pytest.approx(2.268, rel=1e-3)
    with pytest.raises(ValueError):
        convert(1, "kg", "km")
    assert format_number(1234567.0) == "1,234,567" and format_number(2.5) == "2.5"


def test_utils_tools(ctx):
    u = UtilsSkill(ctx)
    assert u.calculate("15% of 80").message == "15% of 80 = **12**"
    assert not u.calculate("1/0").ok
    assert "**6.2137 miles**" in u.convert_units(10, "km", "miles").message
    r = u.time_in("Tokyo")
    assert r.ok and "Tokyo" in r.message
    assert u.time_in("kathmandu").ok
    assert not u.time_in("Atlantis").ok


# ---------- quick rule routing across skills ----------

@pytest.fixture
def router(ctx):
    from test_apps import FakeWindowsApps

    reg = Registry()
    apps = AppsSkill(ctx, FakeWindowsApps())
    apps.refresh()
    reg.extend([apps, NotesSkill(ctx), WebSkill(ctx, opener=Browser()), UtilsSkill(ctx)])
    return QuickMatcher(reg)


@pytest.mark.parametrize("text, tool, args", [
    ("open spotify", "open_app", {"name": "spotify"}),
    ("open google", "open_website", {"site": "google"}),
    ("open youtube", "open_website", {"site": "youtube"}),
    ("go to github.com", "open_website", {"site": "github.com"}),
    ("open github", "open_website", {"site": "github"}),
    ("search best budget laptops", "search_web", {"query": "best budget laptops", "open_in_browser": True}),
    ("search notes for wifi", "search_notes", {"query": "wifi"}),
    ("play lofi beats on youtube", "search_site", {"site": "youtube", "query": "lofi beats"}),
    ("youtube how to tie a tie", "search_site", {"site": "youtube", "query": "how to tie a tie"}),
    ("search amazon for usb c cable", "search_site", {"site": "amazon", "query": "usb c cable"}),
    ("what's the weather", "get_weather", {}),
    ("weather in London tomorrow", "get_weather", {"location": "London"}),
    ("will it rain today", "get_weather", {}),
    ("what is 15% of 2400", "calculate", {"expression": "15% of 2400"}),
    ("12*7", "calculate", {"expression": "12*7"}),
    ("convert 10 km to miles", "convert_units", {"value": 10.0, "from_unit": "km", "to_unit": "miles"}),
    ("100 f in c", "convert_units", {"value": 100.0, "from_unit": "f", "to_unit": "c"}),
    ("what time is it in tokyo", "time_in", {"place": "tokyo"}),
])
def test_routing(router, text, tool, args):
    call = router.match(text)
    assert call is not None, text
    assert (call.name, call.arguments) == (tool, args)


@pytest.mark.parametrize("text", ["what is the capital of france", "open spotify and play jazz", "30",
                                  "tell me a joke", "email ram about the meeting"])
def test_routing_leaves_for_model(router, text):
    assert router.match(text) is None
