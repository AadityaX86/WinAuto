"""Unit conversion tables (length, weight, volume, speed, data, time, area, temperature)."""

from __future__ import annotations

import re

_UNITS: dict[str, tuple[str, float]] = {}


def _add(kind: str, factor: float, *names: str) -> None:
    for n in names:
        _UNITS[n] = (kind, factor)


_add("length", 0.001, "mm", "millimeter", "millimeters", "millimetre", "millimetres")
_add("length", 0.01, "cm", "centimeter", "centimeters", "centimetre", "centimetres")
_add("length", 1, "m", "meter", "meters", "metre", "metres")
_add("length", 1000, "km", "kilometer", "kilometers", "kilometre", "kilometres", "kms")
_add("length", 0.0254, "in", "inch", "inches", '"')
_add("length", 0.3048, "ft", "foot", "feet", "'")
_add("length", 0.9144, "yd", "yard", "yards")
_add("length", 1609.344, "mi", "mile", "miles")
_add("length", 1852, "nmi", "nautical mile", "nautical miles")
_add("mass", 1e-6, "mg", "milligram", "milligrams")
_add("mass", 0.001, "g", "gram", "grams", "gm", "gms")
_add("mass", 1, "kg", "kilo", "kilos", "kilogram", "kilograms", "kgs")
_add("mass", 1000, "t", "tonne", "tonnes", "ton", "tons", "metric ton")
_add("mass", 0.028349523125, "oz", "ounce", "ounces")
_add("mass", 0.45359237, "lb", "lbs", "pound", "pounds")
_add("mass", 6.35029318, "st", "stone", "stones")
_add("volume", 0.001, "ml", "milliliter", "milliliters", "millilitre", "millilitres")
_add("volume", 1, "l", "liter", "liters", "litre", "litres", "ltr")
_add("volume", 0.2365882365, "cup", "cups")
_add("volume", 0.01478676478125, "tbsp", "tablespoon", "tablespoons")
_add("volume", 0.00492892159375, "tsp", "teaspoon", "teaspoons")
_add("volume", 0.0295735295625, "fl oz", "floz", "fluid ounce", "fluid ounces")
_add("volume", 0.473176473, "pint", "pints", "pt")
_add("volume", 0.946352946, "quart", "quarts", "qt")
_add("volume", 3.785411784, "gal", "gallon", "gallons")
_add("volume", 1000, "m3", "cubic meter", "cubic meters", "cubic metre")
_add("speed", 1, "m/s", "mps", "meters per second")
_add("speed", 1 / 3.6, "km/h", "kmh", "kph", "kmph", "kilometers per hour", "km per hour")
_add("speed", 0.44704, "mph", "miles per hour")
_add("speed", 0.514444, "knot", "knots", "kn")
_add("data", 0.125, "bit", "bits")
_add("data", 1, "b", "byte", "bytes")
_add("data", 1e3, "kb", "kilobyte", "kilobytes")
_add("data", 1e6, "mb", "megabyte", "megabytes")
_add("data", 1e9, "gb", "gigabyte", "gigabytes", "gig", "gigs")
_add("data", 1e12, "tb", "terabyte", "terabytes")
_add("data", 1024, "kib")
_add("data", 1024**2, "mib")
_add("data", 1024**3, "gib")
_add("area", 1, "m2", "sq m", "square meter", "square meters", "sqm")
_add("area", 1e6, "km2", "sq km", "square kilometer", "square kilometers")
_add("area", 0.09290304, "ft2", "sq ft", "square foot", "square feet", "sqft")
_add("area", 4046.8564224, "acre", "acres")
_add("area", 10000, "ha", "hectare", "hectares")
_add("time", 1, "s", "sec", "secs", "second", "seconds")
_add("time", 60, "min", "mins", "minute", "minutes")
_add("time", 3600, "h", "hr", "hrs", "hour", "hours")
_add("time", 86400, "day", "days")
_add("time", 604800, "week", "weeks", "wk")
_add("time", 31557600, "year", "years", "yr", "yrs")
_TEMPS = {"c": "C", "celsius": "C", "°c": "C", "centigrade": "C", "f": "F", "fahrenheit": "F", "°f": "F",
          "k": "K", "kelvin": "K"}


def _unit(name: str) -> str:
    n = name.strip().lower().rstrip(".")
    n = re.sub(r"^degrees?\s+", "", n)
    n = n.replace("²", "2").replace("³", "3")
    return n


def convert(value: float, from_unit: str, to_unit: str) -> tuple[float, str, str]:
    f, t = _unit(from_unit), _unit(to_unit)
    if f in _TEMPS and t in _TEMPS:
        a, b = _TEMPS[f], _TEMPS[t]
        c = {"C": value, "F": (value - 32) * 5 / 9, "K": value - 273.15}[a]
        out = {"C": c, "F": c * 9 / 5 + 32, "K": c + 273.15}[b]
        return out, f"°{a}" if a != "K" else "K", f"°{b}" if b != "K" else "K"
    if f not in _UNITS:
        raise ValueError(f"I don't know the unit '{from_unit}'.")
    if t not in _UNITS:
        raise ValueError(f"I don't know the unit '{to_unit}'.")
    (kf, ff), (kt, ft) = _UNITS[f], _UNITS[t]
    if kf != kt:
        raise ValueError(f"Can't convert {kf} ({from_unit}) to {kt} ({to_unit}).")
    return value * ff / ft, from_unit, to_unit


# ---------------- world clock ----------------


def known_unit(name: str) -> bool:
    """True for unit words like 'km' or 'pounds' (so "10 kms to miles" isn't read as currency)."""
    return _unit(name) in _UNITS



def can_convert(from_unit: str, to_unit: str) -> bool:
    """True if both are known units of the same family (both temperatures, or both in the tables)."""
    f, t = _unit(from_unit), _unit(to_unit)
    return (f in _UNITS and t in _UNITS) or (f in _TEMPS and t in _TEMPS)
