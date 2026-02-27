try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
import logging
import os
import random
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class MarketDataConnector:
    """
    Handles integration with external market data providers.
    Supports: Alpha Vantage, Yahoo Finance (via stubs for now).
    """
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://www.alphavantage.co/query"

    async def get_realtime_price(self, ticker: str) -> Dict[str, Any]:
        """
        Fetches real-time price for a ticker.
        """
        if not self.api_key or not AIOHTTP_AVAILABLE:
            # Return stub data if no API key or aiohttp is not available
            return {
                "ticker": ticker,
                "price": round(random.uniform(100, 5000), 2),
                "change_pct": round(random.uniform(-5, 5), 2),
                "source": "Simulation"
            }

        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": ticker,
            "apikey": self.api_key
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.base_url, params=params) as resp:
                    data = await resp.json()
                    quote = data.get("Global Quote", {})
                    if quote:
                        return {
                            "ticker": ticker,
                            "price": float(quote.get("05. price", 0)),
                            "change_pct": float(quote.get("10. change percent", "0%").replace("%", "")),
                            "source": "Alpha Vantage"
                        }
            except Exception as e:
                logger.error(f"Failed to fetch market data for {ticker}: {e}")
        
        return {"error": "Data unavailable"}

    async def get_market_news(self, category: str = "technology") -> List[Dict[str, Any]]:
        """
        Fetches latest financial news stubs.
        """
        # In production, integrate with NewsAPI or similar
        return [
            {"title": f"Market rally continues in {category}", "sentiment": "Bullish", "source": "FinanceFeed"},
            {"title": f"New regulations impact {category} sector", "sentiment": "Neutral", "source": "GlobalNews"}
        ]
