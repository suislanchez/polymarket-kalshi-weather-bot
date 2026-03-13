"""Telegram notifications for trade events.

Setup:
  1. Message @BotFather on Telegram → /newbot → copy the token
  2. Start a chat with your new bot, then get your chat_id:
       curl https://api.telegram.org/bot<TOKEN>/getUpdates
     Look for "chat":{"id": <number>} in the response
  3. Add to .env:
       TELEGRAM_BOT_TOKEN=123456789:ABCdef...
       TELEGRAM_CHAT_ID=987654321
"""
import logging
import httpx
from typing import Optional

logger = logging.getLogger("trading_bot")

_TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _enabled() -> bool:
    from backend.config import settings
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


async def send(message: str, parse_mode: str = "HTML") -> bool:
    """Send a Telegram message. Returns True on success, False on failure."""
    from backend.config import settings

    if not _enabled():
        return False

    url = _TELEGRAM_URL.format(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": parse_mode,
            })
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.debug(f"Telegram send failed: {e}")
        return False


async def notify_order_placed(
    city: str,
    direction: str,
    size_usd: float,
    price: float,
    edge: float,
    order_id: str,
    market_title: str,
):
    msg = (
        f"🟢 <b>LIVE ORDER PLACED</b>\n"
        f"📍 {city} — {market_title}\n"
        f"↗ Direction: <b>{direction.upper()}</b>\n"
        f"💵 Size: <b>${size_usd:.0f}</b> @ {price:.0%}\n"
        f"📊 Edge: <b>{edge:+.1%}</b>\n"
        f"🔑 Order: <code>{order_id[:20]}...</code>"
    )
    await send(msg)


async def notify_trade_settled(
    city: str,
    direction: str,
    size_usd: float,
    result: str,
    pnl: float,
    market_title: str,
):
    icon = "✅" if result == "win" else "❌"
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    msg = (
        f"{icon} <b>TRADE SETTLED — {result.upper()}</b>\n"
        f"📍 {city} — {market_title}\n"
        f"↗ Direction: {direction.upper()}\n"
        f"💵 Size: ${size_usd:.0f}\n"
        f"💰 P&L: <b>{pnl_str}</b>"
    )
    await send(msg)


async def notify_signal_found(
    city: str,
    metric: str,
    direction: str,
    threshold_f: float,
    edge: float,
    model_prob: float,
    market_prob: float,
    platform: str,
):
    msg = (
        f"🔍 <b>WEATHER SIGNAL</b> [{platform.upper()}]\n"
        f"📍 {city}: {metric} <b>{direction}</b> {threshold_f:.0f}°F\n"
        f"📊 Model: {model_prob:.0%} | Market: {market_prob:.0%} | Edge: <b>{edge:+.1%}</b>"
    )
    await send(msg)


async def notify_error(context: str, error: str):
    msg = (
        f"⚠️ <b>BOT ERROR</b>\n"
        f"Context: {context}\n"
        f"Error: <code>{error[:200]}</code>"
    )
    await send(msg)


async def notify_startup(simulation_mode: bool, bankroll: float):
    mode = "SIMULATION" if simulation_mode else "🔴 LIVE TRADING"
    msg = (
        f"🤖 <b>Bot started — {mode}</b>\n"
        f"💰 Bankroll: ${bankroll:,.0f}\n"
        f"Weather scan: every 5 min\n"
        f"Min edge: 8%"
    )
    await send(msg)
