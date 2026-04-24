"""
Travel Scout - Unified Data Integration
Reads shared scraper data for market-aware travel pricing
"""

import sys
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace')

from shared_data_connector import get_crypto, get_news

def check_market_before_travel():
    """Check if markets are stable before suggesting travel"""
    crypto = get_crypto()
    
    # Simple volatility check
    volatile = any(abs(c.change_pct or 0) > 10 for c in crypto)
    
    return {
        'market_volatile': volatile,
        'crypto_snapshot': {c.ticker: c.value for c in crypto[:3]}
    }

if __name__ == "__main__":
    status = check_market_before_travel()
    print(f"Market volatile: {status['market_volatile']}")
    print(f"Prices: {status['crypto_snapshot']}")
