"""Market category classification system."""
from enum import Enum
from typing import Dict, List, Tuple, Optional
import re


class MarketCategory(str, Enum):
    """Supported market categories."""
    WEATHER = "weather"
    CRYPTO = "crypto"
    POLITICS = "politics"
    ECONOMICS = "economics"
    SPORTS = "sports"  # Always excluded from trading
    OTHER = "other"


# Category keyword patterns
CATEGORY_KEYWORDS: Dict[MarketCategory, List[str]] = {
    MarketCategory.WEATHER: [
        "temperature", "temp", "weather", "°f", "°c", "degrees",
        "rain", "snow", "hurricane", "climate", "highest temp",
        "high temp", "low temp", "precipitation", "forecast",
        "heatwave", "cold front", "warm", "hot", "cold", "freezing"
    ],
    MarketCategory.CRYPTO: [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
        "xrp", "ripple", "dogecoin", "doge", "cardano", "ada",
        "polygon", "matic", "avalanche", "avax", "chainlink", "link",
        "price above", "price below", "cryptocurrency", "token",
        "binance", "coinbase", "defi", "nft"
    ],
    MarketCategory.POLITICS: [
        "election", "president", "presidential", "congress", "senate",
        "governor", "vote", "voting", "approval rating", "poll",
        "republican", "democrat", "gop", "dnc", "rnc",
        "primary", "caucus", "nominee", "candidate", "trump", "biden",
        "impeachment", "legislation", "bill passes", "veto"
    ],
    MarketCategory.ECONOMICS: [
        "cpi", "inflation", "gdp", "jobs", "unemployment", "fed",
        "interest rate", "fomc", "payroll", "retail sales",
        "housing", "recession", "federal reserve", "treasury",
        "economic", "pce", "consumer price", "producer price",
        "jobless claims", "employment", "labor", "wage"
    ],
    MarketCategory.SPORTS: [
        "nfl", "nba", "mlb", "nhl", "mls", "pga", "ufc", "mma",
        "soccer", "football", "basketball", "baseball", "hockey",
        "superbowl", "super bowl", "world series", "championship",
        "playoffs", "finals", "tournament", "match", "game",
        "score", "win", "lose", "team", "player", "coach",
        "olympics", "world cup", "grand slam", "masters"
    ]
}


def classify_market(title: str, description: str = "") -> Tuple[MarketCategory, float]:
    """
    Classify a market by its title and description.

    Returns (category, confidence) where confidence is 0-1.
    Higher confidence means more keyword matches.
    """
    text = f"{title} {description}".lower()

    # Count keyword matches for each category
    scores: Dict[MarketCategory, int] = {cat: 0 for cat in MarketCategory}

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in text:
                scores[category] += 1

    # Find best match
    best_category = MarketCategory.OTHER
    best_score = 0
    total_matches = sum(scores.values())

    for category, score in scores.items():
        if score > best_score:
            best_score = score
            best_category = category

    # Calculate confidence based on match ratio
    if total_matches > 0:
        confidence = min(1.0, best_score / 3)  # 3+ matches = full confidence
    else:
        confidence = 0.0

    return best_category, confidence


def is_sports_market(title: str, description: str = "") -> bool:
    """Check if a market is sports-related (should be excluded)."""
    category, confidence = classify_market(title, description)
    return category == MarketCategory.SPORTS and confidence >= 0.3


def get_tradeable_categories() -> List[MarketCategory]:
    """Get list of categories we can trade (excludes sports)."""
    return [
        MarketCategory.WEATHER,
        MarketCategory.CRYPTO,
        MarketCategory.POLITICS,
        MarketCategory.ECONOMICS
    ]


def extract_crypto_asset(title: str) -> Optional[str]:
    """Extract cryptocurrency asset from market title."""
    crypto_patterns = {
        "btc": ["bitcoin", "btc"],
        "eth": ["ethereum", "eth"],
        "sol": ["solana", "sol"],
        "xrp": ["xrp", "ripple"],
        "doge": ["dogecoin", "doge"],
        "ada": ["cardano", "ada"],
        "matic": ["polygon", "matic"],
        "avax": ["avalanche", "avax"],
        "link": ["chainlink", "link"]
    }

    title_lower = title.lower()
    for asset, patterns in crypto_patterns.items():
        for pattern in patterns:
            if pattern in title_lower:
                return asset
    return None


def extract_economic_indicator(title: str) -> Optional[str]:
    """Extract economic indicator from market title."""
    indicator_patterns = {
        "cpi": ["cpi", "consumer price index"],
        "pce": ["pce", "personal consumption"],
        "gdp": ["gdp", "gross domestic product"],
        "unemployment": ["unemployment", "jobless", "labor"],
        "nfp": ["nonfarm payroll", "payroll", "jobs report"],
        "fomc": ["fomc", "federal reserve", "fed rate", "interest rate"],
        "retail": ["retail sales"]
    }

    title_lower = title.lower()
    for indicator, patterns in indicator_patterns.items():
        for pattern in patterns:
            if pattern in title_lower:
                return indicator
    return None


def extract_price_threshold(title: str) -> Optional[Tuple[float, str]]:
    """
    Extract price threshold from crypto/economics market title.

    Returns (threshold_value, direction) or None.
    Direction is 'above' or 'below'.
    """
    # Pattern: "above $50,000" or "below 3.5%"
    above_match = re.search(r'(?:above|over|exceed|higher than)\s*\$?([\d,\.]+)%?', title.lower())
    if above_match:
        try:
            value = float(above_match.group(1).replace(',', ''))
            return (value, 'above')
        except ValueError:
            pass

    below_match = re.search(r'(?:below|under|lower than)\s*\$?([\d,\.]+)%?', title.lower())
    if below_match:
        try:
            value = float(below_match.group(1).replace(',', ''))
            return (value, 'below')
        except ValueError:
            pass

    return None


# Quick test
if __name__ == "__main__":
    test_titles = [
        "Will Bitcoin exceed $100,000 by end of February?",
        "Highest temperature in NYC on February 10?",
        "Will Trump win the Republican primary?",
        "Will CPI inflation be above 3% in January?",
        "Super Bowl winner 2025",
        "Ethereum price above $4,000?",
    ]

    for title in test_titles:
        category, confidence = classify_market(title)
        is_sports = is_sports_market(title)
        print(f"{title[:50]:50} -> {category.value:10} ({confidence:.0%}) {'[EXCLUDED]' if is_sports else ''}")
