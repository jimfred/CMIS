"""Derive Unit / Scale / Byte Order / Conversion Note for a Memory Map field from its spec text.

Scale and Unit are taken literally from the spec: engineering value = raw * Scale, in Unit
(e.g. '1/256 degree Celsius increments' -> Scale 0.00390625, Unit degC; '0.1 uW increments' ->
Scale 0.1, Unit uW). Multi-byte numbers are big-endian in CMIS unless the text says little-endian.
"""
import re

NUMERIC = re.compile(r"^(u8|s8|u16|s16|u32|s32|u64|f16|unspecified|bitfield\d)$")
UNIT = {"degree celsius": "degC", "deg c": "degC", "°c": "degC", "degc": "degC",
        "µv": "uV", "uv": "uV", "mv": "mV", "v": "V", "µa": "uA", "ua": "uA", "ma": "mA",
        "µw": "uW", "uw": "uW", "mw": "mW", "w": "W", "dbm": "dBm", "db": "dB",
        "ghz": "GHz", "mhz": "MHz", "thz": "THz", "nm": "nm", "ns": "ns", "µs": "us", "μs": "us",
        "us": "us", "ms": "ms", "s": "s", "km": "km", "m": "m", "%": "%"}
U = r"(degree Celsius|deg C|°C|µV|uV|mV|V|µA|uA|mA|µW|uW|mW|W|dBm|dB|GHz|MHz|THz|nm|ns|µs|μs|us|ms|s|km|m|%)"
NUM = r"(\d+(?:\.\d+)?(?:\s*/\s*\d+)?)"
PATTERNS = [
    re.compile(r"(?:units? of|increments of|multiples of|resolution of)\s*" + NUM + r"\s*" + U + r"(?![A-Za-z])", re.I),
    re.compile(r"(?:in\s+)?" + NUM + r"\s*" + U + r"(?![A-Za-z])\s*increments", re.I),
    re.compile(r"\bin\s+" + NUM + r"\s*" + U + r"(?![A-Za-z])", re.I),
    re.compile(r"\bin\s+" + U + r"(?![A-Za-z])(?!\s*\d)", re.I),        # "delay in ns" -> scale 1
]
# Field families whose conversion depends on another register (unit/scale left blank, rule in the note)
FAMILY = [
    (r"^Aux1Mon", None, None, "Depends on 01h:145.0: 0b = custom; 1b = TEC current, 100/32767 % of maximum TEC current per LSB (+ heating, - cooling)"),
    (r"^Aux2Mon", None, None, "Depends on 01h:145.1: 0b = laser temperature, 1/256 degC per LSB; 1b = TEC current, 100/32767 % of maximum TEC current per LSB"),
    (r"^Aux3Mon", None, None, "Depends on 01h:145.2: 0b = laser temperature, 1/256 degC per LSB; 1b = additional supply voltage, 100 uV per LSB"),
    (r"^CustomMon", None, None, "Custom monitor: S16 or U16, units defined by the vendor"),
    (r"^LaserBias", "uA", 2.0, "Multiply also by TxBiasCurrentScalingFactor (01h:160.4-3): 00b x1, 01b x2, 10b x4"),
    (r"^BaseLength$", "m", 1.0, "Multiply by LengthMultiplier (00h:202.7-6): 00b x0.1, 01b x1, 10b x10, 11b x100"),
    (r"^BaseLengthSMF$", "km", 1.0, "Multiply by LengthMultiplierSMF (01h:132.7-6): 00b x0.1, 01b x1, 10b x10, 11b per 01h:137"),
    (r"^ModSelWaitTime(Mantissa|Exponent)$", "us", None, "ModSelWaitTime = Mantissa x 2^Exponent us (01h:143)"),
]
TEC = re.compile(r"100\s*%\s*/\s*32767|100\s*/\s*32767\s*%", re.I)


def _num(s):
    s = s.replace(" ", "")
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b)
    return float(s)


def derive(desc, value_type, nbytes, name):
    d = (desc or "").replace(" ", " ")
    out = {"unit": None, "scale": None, "byte_order": None, "conv_note": None}
    if not value_type or not NUMERIC.match(value_type):
        return out
    if nbytes > 1 and value_type != "unspecified" and not value_type.startswith("bitfield"):
        out["byte_order"] = "Little-endian" if re.search(r"little.endian|LSB first", d, re.I) else "Big-endian"
    if value_type == "f16":
        out["conv_note"] = "F16 floating-point encoding (CMIS F16 format)"
        return out
    for pat, unit, scale, note in FAMILY:
        if re.search(pat, name):
            out.update(unit=unit, scale=scale, conv_note=note)
            return out
    if TEC.search(d):
        out.update(unit="%", scale=100 / 32767,
                   conv_note="Percent of maximum TEC current when the Aux monitor is configured as TEC current (01h:145); otherwise custom")
        return out
    for i, p in enumerate(PATTERNS):
        m = p.search(d)
        if not m:
            continue
        if i == 3:
            unit, scale = m.group(1), 1.0
        else:
            scale, unit = _num(m.group(1)), m.group(2)
        out["unit"] = UNIT.get(unit.lower(), unit)
        out["scale"] = scale
        break
    mult = re.search(r"(times the multiplier.*?|[Mm]ust be multiplied by.*?|use multiplier.*?)(?=\s*\(|\.\s|;|$)", d)
    if mult:
        out["conv_note"] = mult.group(1).strip()
    return out
