"""从推文正文提取 $TICKER cashtag。"""
import re

_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
_EXCLUDE = {"USD", "EUR", "GBP", "JPY", "CNY", "BTC", "ETH", "SOL", "AUD", "CAD"}


def extract_tickers(text: str) -> list[str]:
    matches = _CASHTAG_RE.findall(text.upper())
    return sorted(set(m for m in matches if m not in _EXCLUDE))
