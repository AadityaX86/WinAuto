"""Calculator, unit conversion, and world clock.

Small local models make arithmetic mistakes, so they get a real calculator.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from datetime import datetime
from functools import lru_cache

from winauto.core.matching import normalize
from winauto.core.skill import QuickRule, Skill, Suggestion, ToolResult, fail, ok, tool
from winauto.skills.shared.units import can_convert, convert

# ---------------- calculator ----------------

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "sqrt": math.sqrt, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
    "sin": lambda x: math.sin(math.radians(x)), "cos": lambda x: math.cos(math.radians(x)),
    "tan": lambda x: math.tan(math.radians(x)), "log": math.log10, "ln": math.log, "exp": math.exp,
    "min": min, "max": max,
}
_CONSTS = {"pi": math.pi, "e": math.e}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("That power is too big.")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    raise ValueError("I can only do arithmetic here.")


def calculate_expression(expr: str) -> float:
    e = expr.lower().strip().rstrip("=?").strip()
    e = re.sub(r"(?<=\d),(?=\d{3}\b)", "", e)  # 1,000 -> 1000
    e = e.replace("×", "*").replace("÷", "/").replace("^", "**")
    e = re.sub(r"(?<=[\d)\s])x(?=[\s\d(])", "*", e)
    words = {r"\bplus\b": "+", r"\bminus\b": "-", r"\btimes\b": "*", r"\bmultiplied by\b": "*",
             r"\bdivided by\b": "/", r"\bover\b": "/", r"\bsquared\b": "**2", r"\bcubed\b": "**3",
             r"\bto the power of\b": "**", r"\bsquare root of\b": "sqrt"}
    for pattern, rep in words.items():
        e = re.sub(pattern, rep, e)
    # "15% of 80" -> (15/100)*80 ; "200 + 10%" -> 200*(1+10/100)
    e = re.sub(r"([\d.]+)\s*%\s*of\s*", r"(\1/100)*", e)
    e = re.sub(r"([\d.)]+)\s*([+-])\s*([\d.]+)\s*%", r"\1*(1\2\3/100)", e)
    e = re.sub(r"([\d.]+)\s*%", r"(\1/100)", e)
    e = re.sub(r"sqrt\s+([\d.]+)", r"sqrt(\1)", e)
    tree = ast.parse(e, mode="eval")
    return _eval(tree)


def format_number(value: float) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer() and abs(value) < 1e15):
        return f"{int(value):,}"
    if abs(value) >= 1e15 or (abs(value) < 1e-6 and value != 0):
        return f"{value:.6g}"
    text = f"{value:,.6f}".rstrip("0").rstrip(".")
    return text


PLACE_ZONES = {
    "india": "Asia/Kolkata", "delhi": "Asia/Kolkata", "new delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata", "bengaluru": "Asia/Kolkata", "chennai": "Asia/Kolkata", "hyderabad": "Asia/Kolkata",
    "nepal": "Asia/Kathmandu", "pokhara": "Asia/Kathmandu", "china": "Asia/Shanghai", "beijing": "Asia/Shanghai",
    "japan": "Asia/Tokyo", "korea": "Asia/Seoul", "south korea": "Asia/Seoul", "uk": "Europe/London",
    "england": "Europe/London", "britain": "Europe/London", "france": "Europe/Paris", "germany": "Europe/Berlin",
    "spain": "Europe/Madrid", "italy": "Europe/Rome", "netherlands": "Europe/Amsterdam", "russia": "Europe/Moscow",
    "usa": "America/New_York", "us": "America/New_York", "america": "America/New_York",
    "washington": "America/New_York", "washington dc": "America/New_York", "boston": "America/New_York",
    "miami": "America/New_York", "atlanta": "America/New_York", "philadelphia": "America/New_York",
    "chicago": "America/Chicago", "dallas": "America/Chicago", "houston": "America/Chicago",
    "austin": "America/Chicago", "texas": "America/Chicago", "denver": "America/Denver",
    "san francisco": "America/Los_Angeles", "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles",
    "seattle": "America/Los_Angeles", "california": "America/Los_Angeles", "silicon valley": "America/Los_Angeles",
    "las vegas": "America/Los_Angeles", "canada": "America/Toronto", "australia": "Australia/Sydney",
    "melbourne": "Australia/Melbourne", "uae": "Asia/Dubai", "abu dhabi": "Asia/Dubai",
    "saudi arabia": "Asia/Riyadh", "qatar": "Asia/Qatar", "doha": "Asia/Qatar", "pakistan": "Asia/Karachi",
    "islamabad": "Asia/Karachi", "lahore": "Asia/Karachi", "bangladesh": "Asia/Dhaka", "sri lanka": "Asia/Colombo",
    "malaysia": "Asia/Kuala_Lumpur", "thailand": "Asia/Bangkok", "vietnam": "Asia/Ho_Chi_Minh",
    "indonesia": "Asia/Jakarta", "philippines": "Asia/Manila", "brazil": "America/Sao_Paulo",
    "mexico": "America/Mexico_City", "egypt": "Africa/Cairo", "nigeria": "Africa/Lagos", "kenya": "Africa/Nairobi",
    "south africa": "Africa/Johannesburg", "new zealand": "Pacific/Auckland", "turkey": "Europe/Istanbul",
    "israel": "Asia/Jerusalem", "iran": "Asia/Tehran", "utc": "UTC", "gmt": "UTC",
}


@lru_cache(maxsize=1)
def _tz_cities() -> dict[str, str]:
    try:
        from zoneinfo import available_timezones

        zones = available_timezones()
    except Exception:
        return {}
    out = {}
    for z in zones:
        if "/" in z and not z.startswith(("Etc/", "SystemV/", "US/")):
            out[normalize(z.split("/")[-1].replace("_", " "))] = z
    return out


def find_zone(place: str) -> str | None:
    key = normalize(place)
    key = re.sub(r"^(?:the\s+)?", "", key)
    return PLACE_ZONES.get(key) or _tz_cities().get(key)


class UtilsSkill(Skill):
    name = "utils"
    icon = "calculator"
    description = "Calculator, unit conversion, world clock."
    keywords = r"\d|\b(calculate|convert|time in|what time|percent|math)\b"
    always = True
    prompt_hint = "Math: always use calculate for arithmetic or percentages instead of working it out yourself."

    @tool("Calculate a math expression (supports + - * / ^ %, 'of', sqrt, sin...).",
          params={"expression": "e.g. '15% of 2400', '(12+8)*3', 'sqrt(144)'"})
    def calculate(self, expression: str) -> ToolResult:
        try:
            value = calculate_expression(expression)
        except ZeroDivisionError:
            return fail("That divides by zero.")
        except (ValueError, SyntaxError, TypeError, OverflowError) as exc:
            return fail(f"I couldn't calculate '{expression}'. {exc if isinstance(exc, ValueError) else ''}".strip())
        return ok(f"{expression.strip().rstrip('=?')} = **{format_number(value)}**", data={"value": value})

    @tool("Convert between units (length, weight, volume, speed, data, area, time, temperature).",
          params={"value": "The number", "from_unit": "e.g. 'km', 'lb', 'F'", "to_unit": "e.g. 'miles', 'kg', 'C'"})
    def convert_units(self, value: float, from_unit: str, to_unit: str) -> ToolResult:
        try:
            result, a, b = convert(value, from_unit, to_unit)
        except ValueError as exc:
            return fail(str(exc))
        return ok(f"{format_number(value)} {a} = **{format_number(round(result, 4))} {b}**", data={"value": result})

    @tool("Current time in a city or country.", params={"place": "City or country, e.g. 'Tokyo', 'New York'"})
    def time_in(self, place: str) -> ToolResult:
        zone = find_zone(place)
        if not zone:
            return fail(f"I don't know the time zone for '{place}'.")
        from zoneinfo import ZoneInfo

        try:
            now = datetime.now(ZoneInfo(zone))
        except Exception:
            return fail("Time zone data is missing on this PC.")
        local = datetime.now().astimezone()
        diff_h = (now.utcoffset().total_seconds() - local.utcoffset().total_seconds()) / 3600
        rel = "same time as you" if diff_h == 0 else (
            f"{abs(diff_h):g} h {'ahead of' if diff_h > 0 else 'behind'} you")
        return ok(f"It's **{now.strftime('%I:%M %p').lstrip('0')}** on {now.strftime('%A')} in {place.strip().title()} ({rel}).")

    def suggest(self, query: str) -> list[Suggestion]:
        q = re.sub(r"^(?:what(?:'s| is)\s+|calculate\s+|calc\s+|=\s*)", "", query.strip(), flags=re.I).rstrip("=? ")
        out = []
        if re.search(r"\d", q) and re.search(r"[+\-*/^×÷%x]|\bof\b|sqrt|plus|minus|times|divided", q):
            try:
                value = format_number(calculate_expression(q))
                out.append(Suggestion(title=f"= {value}", subtitle=q, tool="set_clipboard", args={"text": value.replace(",", "")},
                                      kind="Copy", icon="calculator", score=99))
            except Exception:
                pass
        m = re.fullmatch(r"(?:convert\s+)?(-?[\d.,]+)\s*([a-z°\"' /²]+?)\s+(?:to|in|into)\s+([a-z° /²]+)", q, re.I)
        if m:
            try:
                result, a, b = convert(float(m.group(1).replace(",", "")), m.group(2), m.group(3))
                value = format_number(round(result, 4))
                out.append(Suggestion(title=f"= {value} {b}", subtitle=f"{m.group(1)} {a}", tool="set_clipboard",
                                      args={"text": value.replace(",", "")}, kind="Copy", icon="calculator", score=99))
            except (ValueError, KeyError):
                pass
        return out

    def quick_rules(self) -> list[QuickRule]:
        def calc(m):
            expr = m["e"].strip()
            if not re.search(r"[+\-*/^×÷%x]|\bof\b|sqrt|plus|minus|times|divided", expr) or not re.search(r"\d", expr):
                return None
            return "calculate", {"expression": expr}

        def conv(m):
            try:
                value = float(m["v"].replace(",", ""))
            except ValueError:
                return None
            if not can_convert(m["f"], m["t"]):
                return None
            return "convert_units", {"value": value, "from_unit": m["f"].strip(), "to_unit": m["t"].strip()}

        return [
            QuickRule(r"(?:what(?:'s| is)\s+|calculate\s+|calc\s+|compute\s+|solve\s+)?"
                      r"(?P<e>[\d\s.,+\-*/^×÷%()x]*\d[\d\s.,+\-*/^×÷%()x]*(?:\s*of\s*[\d.,]+)?|"
                      r"(?:square root of|sqrt)\s*[\d.]+|[\d.]+\s+(?:plus|minus|times|divided by|multiplied by)\s+[\d.]+)\s*=?\??",
                      calc, priority=35),
            QuickRule(r"(?:convert\s+)?(?P<v>-?[\d.,]+)\s*(?P<f>[a-z°\"' /²]+?)\s+(?:to|in|into)\s+(?P<t>[a-z° /²]+)",
                      conv, priority=35),
            QuickRule(r"(?:what(?:'s| is)\s+the\s+)?time\s+(?:is\s+it\s+)?in\s+(?P<p>.+)|what\s+time\s+is\s+it\s+in\s+(?P<p2>.+)",
                      lambda m: ("time_in", {"place": m["p"] or m["p2"]})),
        ]
