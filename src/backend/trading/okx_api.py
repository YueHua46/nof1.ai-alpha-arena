"""
OKX exchange client implementation using CCXT.
Matches the interface required by the BotEngine.
"""

import asyncio
import logging
import ccxt.async_support as ccxt
from typing import Dict, List, Optional, Any
from src.backend.config_loader import CONFIG

class OKXAPI:
    """Facade around OKX CCXT client with convenience methods matching HyperliquidAPI interface."""

    def __init__(self):
        """Initialize OKX CCXT client."""
        self.api_key = CONFIG.get("okx_api_key")
        self.secret_key = CONFIG.get("okx_secret_key")
        self.passphrase = CONFIG.get("okx_passphrase")
        # flag: '0' for simulated trading, '1' for real trading
        self.flag = CONFIG.get("okx_flag", "0")

        if not all([self.api_key, self.secret_key, self.passphrase]):
            raise ValueError("Missing OKX credentials (OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE)")

        self.exchange = ccxt.okx({
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'password': self.passphrase,
            'options': {
                'defaultType': 'swap',  # Target perpetual swaps by default
            }
        })

        if self.flag == '0':
            self.exchange.set_sandbox_mode(True)

        self.markets_loaded = False
        self._ct_val_cache: Dict[str, float] = {}
        self._position_mode: Optional[str] = None  # 'net_mode' or 'long_short_mode'
        
        logging.info(f"OKX 客户端（CCXT）初始化完成（模拟盘：{self.flag == '0'}）")

    async def close(self):
        """Close the exchange connection."""
        await self.exchange.close()

    async def _ensure_markets(self):
        """Ensure markets are loaded."""
        if not self.markets_loaded:
            try:
                await self.exchange.load_markets()
                self.markets_loaded = True
            except Exception as e:
                logging.error(f"Failed to load markets: {e}")
                raise

    def _get_symbol(self, asset: str) -> str:
        """Convert simple asset name to CCXT symbol (e.g. 'BTC' -> 'BTC/USDT:USDT')."""
        if "/" in asset:
            return asset
        return f"{asset}/USDT:USDT"

    def _get_inst_id(self, asset: str) -> str:
        """Convert simple asset name to OKX Instrument ID (e.g. 'BTC' -> 'BTC-USDT-SWAP')."""
        if "-SWAP" in asset:
            return asset
        return f"{asset}-USDT-SWAP"
    
    def _get_asset_from_symbol(self, symbol: str) -> str:
        """Extract simple asset name from CCXT symbol or InstId."""
        # "BTC/USDT:USDT" -> "BTC"
        # "BTC-USDT-SWAP" -> "BTC"
        if "/" in symbol:
            return symbol.split("/")[0]
        if "-USDT-SWAP" in symbol:
            return symbol.replace("-USDT-SWAP", "")
        return symbol

    async def _get_contract_value(self, symbol: str) -> float:
        """Get contract value (contractSize) from market info."""
        await self._ensure_markets()
        try:
            market = self.exchange.market(symbol)
            # For OKX swaps, 'contractSize' in CCXT usually represents the contract value (e.g. 1 contract = 0.01 BTC)
            # depending on the market.
            return float(market.get('contractSize', 1.0))
        except Exception as e:
            logging.error(f"Error fetching contract info for {symbol}: {e}")
            return 1.0

    async def _ensure_position_mode(self) -> None:
        """Detect and cache OKX position mode (net / long_short)."""
        if self._position_mode is not None:
            return
        try:
            res = await self.exchange.private_get_account_config()
            data_list = res.get("data") or []
            data = data_list[0] if data_list else {}
            pos_mode = data.get("posMode")
            if pos_mode in ("net_mode", "long_short_mode"):
                self._position_mode = pos_mode
                logging.info(f"OKX 持仓模式：{pos_mode}")
            else:
                self._position_mode = "net_mode"
                logging.warning(f"未能识别 OKX 持仓模式，默认使用 net_mode：{data}")
        except Exception as e:
            # 保守降级到 net_mode（不传 posSide）
            self._position_mode = "net_mode"
            logging.error(f"获取 OKX 持仓模式失败，将按 net_mode 处理：{e}")

    async def get_user_state(self) -> Dict[str, Any]:
        """Retrieve wallet state and positions."""
        await self._ensure_markets()
        
        balance = 0.0
        total_equity = 0.0
        enriched_positions = []

        try:
            # 1. Get Balance
            # For OKX swap account, we look at the specific currency balance or total equity
            balance_data = await self.exchange.fetch_balance({'type': 'swap'})
            
            # CCXT structures balance: {'USDT': {'free': ..., 'used': ..., 'total': ...}, ...}
            # OKX often has 'info' with more details
            
            if 'USDT' in balance_data:
                balance = float(balance_data['USDT'].get('free', 0.0))
            
            # Try to get total equity from info if available (depends on account mode)
            # balance_data['info'] is the raw response from OKX
            if 'info' in balance_data and 'data' in balance_data['info']:
                data_list = balance_data['info']['data']
                if data_list and len(data_list) > 0:
                    total_equity = float(data_list[0].get('totalEq', 0.0))
            
            if total_equity == 0.0 and 'USDT' in balance_data:
                 # Fallback
                 total_equity = float(balance_data['USDT'].get('total', 0.0))

            # 2. Get Positions
            positions = await self.exchange.fetch_positions()
            
            for pos in positions:
                # pos structure normalized by CCXT
                symbol = pos['symbol'] # e.g. BTC/USDT:USDT
                asset = self._get_asset_from_symbol(symbol)
                
                contracts = float(pos['contracts']) if pos['contracts'] else 0.0
                if contracts == 0:
                    continue
                
                side = pos['side'] # 'long' or 'short'
                entry_px = float(pos['entryPrice'] or 0)
                mark_px = float(pos['markPrice'] or 0)
                upl = float(pos['unrealizedPnl'] or 0)
                leverage = float(pos['leverage'] or 1)
                liq_px = float(pos['liquidationPrice'] or 0)
                
                # OKX specific handling for size in coins
                # contracts * contractSize = amount in base currency (usually)
                contract_size = float(pos.get('contractSize', 1.0))
                size_coins = contracts * contract_size
                
                if side == 'short':
                    size_coins = -abs(size_coins)
                else:
                    size_coins = abs(size_coins)

                enriched_positions.append({
                    "symbol": asset,
                    "coin": asset,
                    "quantity": size_coins,
                    "entry_price": entry_px,
                    "current_price": mark_px,
                    "liquidation_price": liq_px,
                    "unrealized_pnl": upl,
                    "leverage": leverage,
                    "pnl": upl,
                    "szi": size_coins,
                    "entryPx": entry_px
                })

        except Exception as e:
            logging.error(f"Failed to fetch user state: {e}")

        return {
            "balance": balance,
            "total_value": total_equity,
            "positions": enriched_positions,
            "withdrawable": balance,
            "accountValue": total_equity,
            "assetPositions": [{"position": p} for p in enriched_positions]
        }

    async def get_current_price(self, asset: str) -> float:
        """Return the latest price for asset."""
        await self._ensure_markets()
        symbol = self._get_symbol(asset)
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return float(ticker['last'])
        except Exception as e:
            logging.error(f"Error fetching price for {asset}: {e}")
            return 0.0

    async def place_buy_order(self, asset: str, amount: float, slippage: float = 0.01) -> Dict:
        """Submit a market buy order."""
        return await self._place_market_order(asset, 'buy', amount)

    async def place_sell_order(self, asset: str, amount: float, slippage: float = 0.01) -> Dict:
        """Submit a market sell order."""
        return await self._place_market_order(asset, 'sell', amount)

    async def _place_market_order(self, asset: str, side: str, amount: float) -> Dict:
        await self._ensure_markets()
        await self._ensure_position_mode()
        symbol = self._get_symbol(asset)
        
        # OKX requires amount in contracts for swaps
        ct_val = await self._get_contract_value(symbol)
        
        # amount is in coins (e.g. 0.1 BTC)
        # contracts = amount / contract_value
        sz_contracts = int(amount / ct_val) if ct_val > 0 else 1
        
        if sz_contracts == 0:
            logging.warning(f"Amount {amount} is too small for {symbol} (ctVal: {ct_val})")
            return {"code": "error", "msg": "Amount too small"}

        logging.info(f"准备下 {side.upper()} 单：{symbol}，数量 {amount} {asset}，折合 {sz_contracts} 张合约")
        
        try:
            # Use exchange-specific params for tdMode if needed, though CCXT defaultType='swap' usually handles it.
            # Passing 'tdMode': 'cross' explicitly to be safe.
            params: Dict[str, Any] = {'tdMode': 'cross'}
            # 在逐仓多空分离模式下，需要显式提供 posSide
            if self._position_mode == "long_short_mode":
                params["posSide"] = "long" if side == "buy" else "short"
            res = await self.exchange.create_order(symbol, 'market', side, sz_contracts, params=params)
            return res
        except Exception as e:
            logging.error(f"Error placing order: {e}")
            raise e

    async def place_take_profit(self, asset: str, is_buy: bool, amount: float, tp_price: float) -> Dict:
        """Place TP order using algo order."""
        await self._ensure_markets()
        await self._ensure_position_mode()
        inst_id = self._get_inst_id(asset)
        symbol = self._get_symbol(asset)
        
        ct_val = await self._get_contract_value(symbol)
        sz_contracts = str(int(amount / ct_val)) if ct_val > 0 else "1"
        
        side = "sell" if is_buy else "buy"
        
        # Use private API directly to ensure correct OKX algo order params
        params: Dict[str, Any] = {
            'instId': inst_id,
            'tdMode': 'cross',
            'side': side,
            'ordType': 'conditional',
            'sz': sz_contracts,
            'tpTriggerPx': str(tp_price),
            'tpOrdPx': '-1'  # Market price when triggered
        }
        # long_short_mode 下需要指定 posSide（以原始持仓方向为准）
        if self._position_mode == "long_short_mode":
            params["posSide"] = "long" if is_buy else "short"
        
        try:
            return await self.exchange.private_post_trade_order_algo(params)
        except Exception as e:
            logging.error(f"Error placing TP: {e}")
            raise e

    async def place_stop_loss(self, asset: str, is_buy: bool, amount: float, sl_price: float) -> Dict:
        """Place SL order using algo order."""
        await self._ensure_markets()
        await self._ensure_position_mode()
        inst_id = self._get_inst_id(asset)
        symbol = self._get_symbol(asset)
        
        ct_val = await self._get_contract_value(symbol)
        sz_contracts = str(int(amount / ct_val)) if ct_val > 0 else "1"
        
        side = "sell" if is_buy else "buy"
        
        params: Dict[str, Any] = {
            'instId': inst_id,
            'tdMode': 'cross',
            'side': side,
            'ordType': 'conditional',
            'sz': sz_contracts,
            'slTriggerPx': str(sl_price),
            'slOrdPx': '-1'  # Market price when triggered
        }
        if self._position_mode == "long_short_mode":
            params["posSide"] = "long" if is_buy else "short"
        
        try:
            return await self.exchange.private_post_trade_order_algo(params)
        except Exception as e:
            logging.error(f"Error placing SL: {e}")
            raise e

    async def cancel_order(self, asset: str, oid: str) -> Dict:
        """Cancel an order (regular or algo)."""
        await self._ensure_markets()
        symbol = self._get_symbol(asset)
        inst_id = self._get_inst_id(asset)
        
        # Try cancelling as regular order first
        try:
            return await self.exchange.cancel_order(oid, symbol)
        except Exception:
            # If not found or error, try cancelling as algo order
            try:
                return await self.exchange.private_post_trade_cancel_algo_order([{'instId': inst_id, 'algoId': oid}])
            except Exception as e:
                logging.error(f"Error cancelling order {oid}: {e}")
                return {"code": "error", "msg": str(e)}

    async def cancel_all_orders(self, asset: str) -> Dict:
        """Cancel all open orders for asset."""
        await self._ensure_markets()
        symbol = self._get_symbol(asset)
        inst_id = self._get_inst_id(asset)
        
        try:
            # 1. Regular orders
            # CCXT cancel_all_orders implementation for OKX usually works well
            await self.exchange.cancel_all_orders(symbol)
            
            # 2. Algo orders (fetch pending then cancel)
            # Need to use private API to find pending algo orders
            algo_orders_res = await self.exchange.private_get_trade_orders_algo_pending({'instType': 'SWAP', 'instId': inst_id})
            if algo_orders_res.get('code') == '0' and algo_orders_res.get('data'):
                algo_ids = [{'instId': inst_id, 'algoId': o['algoId']} for o in algo_orders_res['data']]
                if algo_ids:
                    await self.exchange.private_post_trade_cancel_algo_order(algo_ids)
            
            return {"status": "ok"}
        except Exception as e:
            logging.error(f"Error cancelling all orders: {e}")
            return {"status": "error", "msg": str(e)}

    async def get_open_orders(self) -> List[Dict]:
        """Get all open orders (regular and algo)."""
        await self._ensure_markets()
        orders = []
        
        try:
            # 1. Regular orders using Raw API to get all SWAP orders at once
            # (CCXT fetchOpenOrders might require symbol or multiple calls)
            res = await self.exchange.private_get_trade_orders_pending({'instType': 'SWAP'})
            if res.get('code') == '0':
                for o in res.get('data', []):
                    inst_id = o['instId']
                    symbol = self._get_symbol(self._get_asset_from_symbol(inst_id))
                    
                    ct_val = await self._get_contract_value(symbol)
                    sz_contracts = float(o.get('sz', 0))
                    size_coins = sz_contracts * ct_val
                    
                    orders.append({
                        "coin": self._get_asset_from_symbol(inst_id),
                        "oid": o["ordId"],
                        "is_buy": o["side"] == "buy",
                        "size": size_coins,
                        "price": float(o.get("px", 0) or 0),
                        "trigger_price": None,
                        "order_type": o["ordType"]
                    })
            
            # 2. Algo orders
            res_algo = await self.exchange.private_get_trade_orders_algo_pending({'instType': 'SWAP', 'ordType': 'conditional'})
            if res_algo.get('code') == '0':
                 for o in res_algo.get('data', []):
                    inst_id = o['instId']
                    symbol = self._get_symbol(self._get_asset_from_symbol(inst_id))
                    
                    ct_val = await self._get_contract_value(symbol)
                    sz_contracts = float(o.get('sz', 0))
                    size_coins = sz_contracts * ct_val
                    
                    trigger_px = o.get("tpTriggerPx") or o.get("slTriggerPx")
                    orders.append({
                        "coin": self._get_asset_from_symbol(inst_id),
                        "oid": o["algoId"],
                        "is_buy": o["side"] == "buy",
                        "size": size_coins,
                        "price": float(o.get("ordPx", 0) or -1),
                        "trigger_price": float(trigger_px) if trigger_px else None,
                        "order_type": "trigger"
                    })

        except Exception as e:
            logging.error(f"Error fetching open orders: {e}")
            
        return orders

    async def get_recent_fills(self, limit: int = 50) -> List[Dict]:
        """Get recent trades."""
        await self._ensure_markets()
        fills = []
        try:
            # Use raw API to get fills for all swaps
            res = await self.exchange.private_get_trade_fills({'instType': 'SWAP', 'limit': str(limit)})
            if res.get('code') == '0':
                for f in res.get('data', []):
                    inst_id = f['instId']
                    symbol = self._get_symbol(self._get_asset_from_symbol(inst_id))
                    
                    ct_val = await self._get_contract_value(symbol)
                    sz_contracts = float(f.get('sz', 0))
                    size_coins = sz_contracts * ct_val
                    
                    fills.append({
                        "timestamp": f.get("ts"),
                        "coin": self._get_asset_from_symbol(inst_id),
                        "is_buy": f["side"] == "buy",
                        "size": size_coins,
                        "price": float(f.get("fillPx", 0))
                    })
        except Exception as e:
            logging.error(f"Error fetching fills: {e}")
            
        return fills

    def extract_oids(self, order_result: Dict) -> List[str]:
        """Extract Order IDs from response."""
        oids = []
        # CCXT normalized 'id'
        if 'id' in order_result:
            oids.append(order_result['id'])
        
        # Check raw 'data' if it's a direct API response structure
        # (CCXT create_order returns a dict that includes 'info' with raw data)
        if 'info' in order_result and isinstance(order_result['info'], dict):
             raw_data = order_result['info'].get('data', [])
             if raw_data:
                 for d in raw_data:
                     if 'ordId' in d:
                         oids.append(d['ordId'])
                     if 'algoId' in d:
                         oids.append(d['algoId'])

        # Fallback: if order_result is just the raw OKX response dict (not CCXT structure)
        if order_result.get("code") == "0" and order_result.get("data"):
            for d in order_result["data"]:
                if "ordId" in d:
                    oids.append(d["ordId"])
                if "algoId" in d:
                    oids.append(d["algoId"])
                    
        # Deduplicate
        return list(set(oids))

    async def get_open_interest(self, asset: str) -> Optional[float]:
        """Get Open Interest."""
        await self._ensure_markets()
        symbol = self._get_symbol(asset)
        try:
            res = await self.exchange.fetch_open_interest(symbol)
            return float(res.get('openInterestAmount', 0)) # or res['openInterest'] depending on CCXT version normalization
        except Exception:
            return None

    async def get_funding_rate(self, asset: str) -> Optional[float]:
        """Get Funding Rate."""
        await self._ensure_markets()
        symbol = self._get_symbol(asset)
        try:
            res = await self.exchange.fetch_funding_rate(symbol)
            return float(res.get('fundingRate', 0))
        except Exception:
            return None
