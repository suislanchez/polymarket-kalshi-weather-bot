"""Claude AI integration for deep signal analysis."""
import time
from typing import Optional, List, Dict, Any
import logging

from .base import (
    AIAnalysis, AnomalyReport, TradeRecommendation, BaseAIClient,
    create_signal_prompt
)

logger = logging.getLogger(__name__)


class ClaudeAnalyzer(BaseAIClient):
    """
    Claude-powered analyzer for:
    - Deep signal reasoning
    - Trade decision analysis
    - Market anomaly detection
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazy load the Anthropic client."""
        if self._client is None:
            if not self.api_key:
                from backend.config import settings
                self.api_key = settings.ANTHROPIC_API_KEY

            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")

            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("anthropic package not installed. Run: pip install anthropic")

        return self._client

    async def analyze_signal(
        self,
        signal_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> AIAnalysis:
        """
        Analyze a trading signal with Claude for enhanced reasoning.

        Args:
            signal_data: Signal information (ticker, edge, probabilities, etc.)
            context: Additional context (weather data, crypto prices, etc.)

        Returns:
            AIAnalysis with reasoning and confidence
        """
        start_time = time.time()

        try:
            client = self._get_client()
            prompt = create_signal_prompt(signal_data, context)

            message = client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = message.content[0].text
            tokens_used = message.usage.input_tokens + message.usage.output_tokens
            latency_ms = (time.time() - start_time) * 1000

            # Parse confidence from response (simple heuristic)
            confidence = 0.7  # Default
            if "high confidence" in response_text.lower():
                confidence = 0.85
            elif "low confidence" in response_text.lower():
                confidence = 0.4
            elif "uncertain" in response_text.lower():
                confidence = 0.5

            # Extract risk factors
            risk_factors = []
            if "risk" in response_text.lower():
                # Simple extraction - could be enhanced with more parsing
                risk_factors = ["Market volatility", "Model uncertainty"]

            return AIAnalysis(
                reasoning=response_text,
                confidence=confidence,
                recommendation=None,
                risk_factors=risk_factors,
                raw_response=response_text,
                model_used=self.model,
                provider="claude",
                latency_ms=latency_ms,
                tokens_used=tokens_used
            )

        except Exception as e:
            logger.error(f"Claude analysis failed: {e}")
            latency_ms = (time.time() - start_time) * 1000
            return AIAnalysis(
                reasoning=f"Analysis unavailable: {str(e)}",
                confidence=0.0,
                raw_response="",
                model_used=self.model,
                provider="claude",
                latency_ms=latency_ms,
                tokens_used=0
            )

    async def classify_market(
        self,
        title: str,
        description: str = ""
    ) -> tuple[str, float]:
        """Classify market using Claude (for complex cases)."""
        # For classification, prefer Groq for speed
        # Claude is used as fallback for complex cases
        try:
            client = self._get_client()

            prompt = f"""Classify this prediction market. Respond with ONLY the category name.

Title: {title}

Categories: weather, crypto, politics, economics, sports, other"""

            message = client.messages.create(
                model=self.model,
                max_tokens=50,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response = message.content[0].text.strip().lower()

            # Map response to category
            valid_categories = ["weather", "crypto", "politics", "economics", "sports", "other"]
            for cat in valid_categories:
                if cat in response:
                    return (cat, 0.8)

            return ("other", 0.5)

        except Exception as e:
            logger.error(f"Claude classification failed: {e}")
            return ("other", 0.0)

    async def detect_anomalies(
        self,
        markets: List[Dict[str, Any]]
    ) -> List[AnomalyReport]:
        """Detect anomalies in market data using Claude."""
        if not markets:
            return []

        try:
            client = self._get_client()

            # Build market summary
            market_summary = "\n".join([
                f"- {m.get('ticker', 'Unknown')}: ${m.get('yes_price', 0):.2f} YES, "
                f"${m.get('volume', 0):,.0f} volume"
                for m in markets[:20]  # Limit to 20 markets
            ])

            prompt = f"""Analyze these prediction markets for anomalies:

{market_summary}

Look for:
1. Unusual price movements (far from 0.5)
2. Very low or very high volume compared to peers
3. Prices that seem mispriced based on the market title

List any anomalies found. If none, say "No anomalies detected."
Be concise (1-2 sentences per anomaly)."""

            message = client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response = message.content[0].text

            # Parse anomalies from response
            anomalies = []
            if "no anomalies" not in response.lower():
                # Simple parsing - could be enhanced
                for line in response.split("\n"):
                    if line.strip() and any(m.get('ticker', '') in line for m in markets):
                        anomalies.append(AnomalyReport(
                            market_ticker=line.split(":")[0].strip() if ":" in line else "Unknown",
                            anomaly_type="ai_detected",
                            severity="medium",
                            description=line.strip(),
                            ai_analysis=response
                        ))

            return anomalies

        except Exception as e:
            logger.error(f"Claude anomaly detection failed: {e}")
            return []

    async def analyze_trade_decision(
        self,
        signal_data: Dict[str, Any],
        portfolio_state: Dict[str, Any]
    ) -> TradeRecommendation:
        """Deep analysis of whether to execute a specific trade."""
        try:
            client = self._get_client()

            prompt = f"""Should we execute this trade?

Signal:
- Market: {signal_data.get('market_title', 'Unknown')}
- Direction: {signal_data.get('direction', 'Unknown')}
- Edge: {signal_data.get('edge', 0):.1%}
- Suggested Size: ${signal_data.get('suggested_size', 0):.2f}

Portfolio:
- Bankroll: ${portfolio_state.get('bankroll', 0):,.2f}
- Current P&L: ${portfolio_state.get('total_pnl', 0):,.2f}
- Pending Trades: {portfolio_state.get('pending_trades', 0)}

Provide:
1. Should trade? (yes/no)
2. Recommended size adjustment (if any)
3. Key risks (bullet points)
4. Confidence (0-100)

Be concise."""

            message = client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response = message.content[0].text

            # Parse response
            should_trade = "yes" in response.lower()[:50]

            # Extract confidence
            confidence = 0.6
            import re
            conf_match = re.search(r'confidence[:\s]*(\d+)', response.lower())
            if conf_match:
                confidence = int(conf_match.group(1)) / 100

            return TradeRecommendation(
                signal_ticker=signal_data.get('market_ticker', ''),
                should_trade=should_trade,
                recommended_size=signal_data.get('suggested_size'),
                reasoning=response,
                risk_assessment="See reasoning",
                confidence=confidence,
                caveats=[]
            )

        except Exception as e:
            logger.error(f"Claude trade analysis failed: {e}")
            return TradeRecommendation(
                signal_ticker=signal_data.get('market_ticker', ''),
                should_trade=True,  # Default to deterministic signal
                reasoning=f"AI analysis unavailable: {e}",
                confidence=0.5
            )
