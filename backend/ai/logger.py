"""AI call logging for monitoring and debugging."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class AICallRecord:
    """Record of an AI API call."""
    timestamp: str
    provider: str
    model: str
    prompt: str
    response: str
    latency_ms: float
    tokens_used: int
    cost_usd: float
    related_market: Optional[str] = None
    call_type: str = "unknown"  # "classification", "analysis", "anomaly"
    success: bool = True
    error: Optional[str] = None


class AICallLogger:
    """
    Comprehensive logger for all AI API calls.

    Logs to:
    1. File (JSON lines format)
    2. Database (if session provided)
    3. Console (debug level)
    """

    # Approximate costs per 1M tokens (as of early 2025)
    COSTS = {
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
        "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
        "llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
        "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
        "mixtral-8x7b-32768": {"input": 0.24, "output": 0.24},
    }

    def __init__(self, log_dir: str = "logs/ai", log_to_db: bool = True):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_to_db = log_to_db
        self._log_file = self.log_dir / f"ai_calls_{datetime.now().strftime('%Y%m%d')}.jsonl"

    def estimate_cost(self, model: str, tokens_used: int) -> float:
        """Estimate cost of an API call in USD."""
        if model not in self.COSTS:
            return 0.0

        # Assume 50/50 split between input/output tokens
        costs = self.COSTS[model]
        avg_cost = (costs["input"] + costs["output"]) / 2
        return (tokens_used / 1_000_000) * avg_cost

    def log_call(
        self,
        provider: str,
        model: str,
        prompt: str,
        response: str,
        latency_ms: float,
        tokens_used: int,
        related_market: Optional[str] = None,
        call_type: str = "unknown",
        success: bool = True,
        error: Optional[str] = None
    ) -> AICallRecord:
        """
        Log an AI API call.

        Args:
            provider: "claude" or "groq"
            model: Model name/ID
            prompt: Input prompt
            response: Model response
            latency_ms: Call latency in milliseconds
            tokens_used: Total tokens used
            related_market: Market ticker if applicable
            call_type: Type of call (classification, analysis, etc.)
            success: Whether call succeeded
            error: Error message if failed

        Returns:
            AICallRecord for the logged call
        """
        cost_usd = self.estimate_cost(model, tokens_used)

        record = AICallRecord(
            timestamp=datetime.utcnow().isoformat(),
            provider=provider,
            model=model,
            prompt=prompt[:1000],  # Truncate long prompts
            response=response[:2000],  # Truncate long responses
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            related_market=related_market,
            call_type=call_type,
            success=success,
            error=error
        )

        # Log to file
        self._write_to_file(record)

        # Log to console
        log_msg = (
            f"AI Call: {provider}/{model} | {call_type} | "
            f"{latency_ms:.0f}ms | {tokens_used} tokens | ${cost_usd:.4f}"
        )
        if success:
            logger.debug(log_msg)
        else:
            logger.warning(f"{log_msg} | ERROR: {error}")

        return record

    def _write_to_file(self, record: AICallRecord):
        """Write record to JSON lines file."""
        try:
            with open(self._log_file, "a") as f:
                f.write(json.dumps(asdict(record)) + "\n")
        except Exception as e:
            logger.error(f"Failed to write AI log: {e}")

    async def log_to_database(self, record: AICallRecord, db_session):
        """Write record to database."""
        if not self.log_to_db:
            return

        try:
            from backend.models.database import AILog

            db_record = AILog(
                timestamp=datetime.fromisoformat(record.timestamp),
                provider=record.provider,
                model=record.model,
                prompt=record.prompt,
                response=record.response,
                latency_ms=record.latency_ms,
                tokens_used=record.tokens_used,
                cost_usd=record.cost_usd,
                related_market=record.related_market
            )
            db_session.add(db_record)
            db_session.commit()
        except Exception as e:
            logger.error(f"Failed to log AI call to database: {e}")

    def get_daily_stats(self) -> Dict[str, Any]:
        """Get statistics for today's AI calls."""
        stats = {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0.0,
            "by_provider": {},
            "by_call_type": {},
            "errors": 0
        }

        try:
            if not self._log_file.exists():
                return stats

            latencies = []
            with open(self._log_file, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        stats["total_calls"] += 1
                        stats["total_tokens"] += record.get("tokens_used", 0)
                        stats["total_cost_usd"] += record.get("cost_usd", 0)
                        latencies.append(record.get("latency_ms", 0))

                        if not record.get("success", True):
                            stats["errors"] += 1

                        # By provider
                        provider = record.get("provider", "unknown")
                        if provider not in stats["by_provider"]:
                            stats["by_provider"][provider] = 0
                        stats["by_provider"][provider] += 1

                        # By call type
                        call_type = record.get("call_type", "unknown")
                        if call_type not in stats["by_call_type"]:
                            stats["by_call_type"][call_type] = 0
                        stats["by_call_type"][call_type] += 1

                    except json.JSONDecodeError:
                        continue

            if latencies:
                stats["avg_latency_ms"] = sum(latencies) / len(latencies)

        except Exception as e:
            logger.error(f"Failed to get AI stats: {e}")

        return stats


# Global logger instance
_ai_logger: Optional[AICallLogger] = None


def get_ai_logger() -> AICallLogger:
    """Get or create the global AI logger instance."""
    global _ai_logger
    if _ai_logger is None:
        _ai_logger = AICallLogger()
    return _ai_logger
