"""Base classes and types for AI integration."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class AIProvider(str, Enum):
    """Supported AI providers."""
    CLAUDE = "claude"
    GROQ = "groq"


@dataclass
class AIAnalysis:
    """Result of AI analysis on a market or signal."""
    reasoning: str
    confidence: float  # 0-1
    recommendation: Optional[str] = None
    risk_factors: List[str] = field(default_factory=list)
    raw_response: str = ""
    model_used: str = ""
    provider: str = ""
    latency_ms: float = 0.0
    tokens_used: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "recommendation": self.recommendation,
            "risk_factors": self.risk_factors,
            "model_used": self.model_used,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class AnomalyReport:
    """Report of detected market anomaly."""
    market_ticker: str
    anomaly_type: str  # "price_spike", "volume_anomaly", "spread_unusual"
    severity: str  # "low", "medium", "high"
    description: str
    detected_at: datetime = field(default_factory=datetime.utcnow)
    ai_analysis: Optional[str] = None


@dataclass
class TradeRecommendation:
    """AI-generated trade recommendation."""
    signal_ticker: str
    should_trade: bool
    recommended_size: Optional[float] = None
    reasoning: str = ""
    risk_assessment: str = ""
    confidence: float = 0.5
    caveats: List[str] = field(default_factory=list)


class BaseAIClient(ABC):
    """Abstract base class for AI clients."""

    @abstractmethod
    async def analyze_signal(
        self,
        signal_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> AIAnalysis:
        """Analyze a trading signal and provide reasoning."""
        pass

    @abstractmethod
    async def classify_market(
        self,
        title: str,
        description: str = ""
    ) -> tuple[str, float]:
        """Classify a market into a category."""
        pass

    @abstractmethod
    async def detect_anomalies(
        self,
        markets: List[Dict[str, Any]]
    ) -> List[AnomalyReport]:
        """Detect anomalies in market data."""
        pass


def create_signal_prompt(signal_data: Dict[str, Any], context: Dict[str, Any] = None) -> str:
    """Create a prompt for signal analysis."""
    prompt = f"""Analyze this prediction market trading signal:

Market: {signal_data.get('market_title', 'Unknown')}
Platform: {signal_data.get('platform', 'Unknown')}
Category: {signal_data.get('category', 'Unknown')}

Model Probability: {signal_data.get('model_probability', 0):.1%}
Market Price: {signal_data.get('market_probability', 0):.1%}
Edge: {signal_data.get('edge', 0):.1%}
Suggested Size: ${signal_data.get('suggested_size', 0):.2f}

Direction: {signal_data.get('direction', 'Unknown').upper()}
"""

    if context:
        if 'weather_data' in context:
            wd = context['weather_data']
            prompt += f"""
Weather Context:
- High Temperature Forecast: {wd.get('high_temp', 'N/A')}°F
- Ensemble Agreement: {wd.get('confidence', 0):.0%}
- Number of Models: {wd.get('ensemble_count', 'N/A')}
"""
        if 'crypto_data' in context:
            cd = context['crypto_data']
            prompt += f"""
Crypto Context:
- Current Price: ${cd.get('current_price', 'N/A'):,.2f}
- 24h Change: {cd.get('change_24h', 0):.1%}
- Market Cap: ${cd.get('market_cap', 0):,.0f}
"""

    prompt += """
Provide a brief analysis (2-3 sentences) covering:
1. Why this edge might exist
2. Key risk factors
3. Confidence in the model's probability estimate

Be concise and actionable."""

    return prompt


def create_classification_prompt(title: str, description: str = "") -> str:
    """Create a prompt for market classification."""
    return f"""Classify this prediction market into one category:

Title: {title}
Description: {description or 'N/A'}

Categories:
- weather: Temperature, precipitation, climate events
- crypto: Cryptocurrency prices, blockchain events
- politics: Elections, legislation, government actions
- economics: Inflation, GDP, employment, Fed decisions
- sports: Any sports-related markets (games, scores, tournaments)
- other: Doesn't fit above categories

Respond with just the category name (lowercase) and confidence (0-100).
Format: category,confidence

Example: crypto,85"""
