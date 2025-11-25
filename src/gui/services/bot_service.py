"""
Bot Service - Manages bot lifecycle and provides data access for GUI
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from src.backend.bot_engine import TradingBotEngine, BotState
from src.backend.config_loader import CONFIG
from src.backend.trading.okx_api import OKXAPI


class BotService:
    """Service layer for bot management and data access"""

    def __init__(self):
        self.bot_engine: Optional[TradingBotEngine] = None
        self.state_manager = None  # Set externally after creation
        self.equity_history: List[Dict] = []
        self.recent_events: List[Dict] = []
        self.logger = logging.getLogger(__name__)

        # Configuration
        self.config = {
            'assets': CONFIG.get('assets', '').split() if CONFIG.get('assets') else ['BTC', 'ETH'],
            'interval': CONFIG.get('interval', '5m'),
            'model': CONFIG.get('llm_model', 'x-ai/grok-4')
        }
        
        # Load configuration from file if exists (overrides env vars)
        self._load_config_file()

    async def start(self, assets: Optional[List[str]] = None, interval: Optional[str] = None):
        """
        Start the trading bot.

        Args:
            assets: List of assets to trade (optional, uses config if not provided)
            interval: Trading interval (optional, uses config if not provided)
        """
        if self.bot_engine and self.bot_engine.is_running:
            self.logger.warning("交易机器人已在运行，忽略重复启动请求")
            return

        # Validate API keys before starting
        if not CONFIG.get('taapi_api_key'):
            raise ValueError("TAAPI_API_KEY not configured. Please set it in .env file.")
        if not CONFIG.get('llm_api_key'):
            raise ValueError("LLM_API_KEY not configured. Please set it in .env file.")
        if not CONFIG.get('okx_api_key'):
            raise ValueError("Exchange credentials (OKX) not configured. Please set them in .env file.")

        # Use provided values or fall back to config
        assets = assets or self.config['assets']
        interval = interval or self.config['interval']

        if not assets or not interval:
            raise ValueError("Assets and interval must be configured. Set ASSETS and INTERVAL in .env file.")

        try:
            # Create bot engine with callbacks
            self.bot_engine = TradingBotEngine(
                assets=assets,
                interval=interval,
                on_state_update=self._on_state_update,
                on_trade_executed=self._on_trade_executed,
                on_error=self._on_error
            )

            # Start the bot
            await self.bot_engine.start()

            self.logger.info(f"交易机器人启动成功，资产：{assets}，周期：{interval}")

        except Exception as e:
            self.logger.error(f"启动交易机器人失败：{e}", exc_info=True)
            raise

    async def stop(self):
        """Stop the trading bot"""
        if not self.bot_engine:
            return

        try:
            await self.bot_engine.stop()
            self.logger.info("交易机器人已成功停止")
        except Exception as e:
            self.logger.error(f"停止交易机器人时出错：{e}", exc_info=True)
            raise

    def is_running(self) -> bool:
        """Check if bot is currently running"""
        return self.bot_engine is not None and self.bot_engine.is_running

    def get_state(self) -> BotState:
        """Get current bot state"""
        if self.bot_engine:
            return self.bot_engine.get_state()
        return BotState()

    def get_equity_history(self, limit: int = 100) -> List[Dict]:
        """
        Get equity curve history for charting.

        Returns:
            List of dicts with 'time' and 'value' keys
        """
        return self.equity_history[-limit:]

    def get_recent_events(self, limit: int = 20) -> List[Dict]:
        """
        Get recent activity events for activity feed.

        Returns:
            List of event dicts with 'time' and 'message' keys
        """
        return self.recent_events[-limit:]

    def get_trade_history(
        self,
        asset: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get trade history from diary.jsonl with optional filtering.

        Args:
            asset: Filter by asset (optional)
            action: Filter by action (buy/sell/hold) (optional)
            limit: Maximum number of entries to return

        Returns:
            List of trade entries
        """
        diary_path = Path("data/diary.jsonl")
        if not diary_path.exists():
            return []

        try:
            entries = []
            with open(diary_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)

                            # Apply filters
                            if asset and entry.get('asset') != asset:
                                continue
                            if action and entry.get('action') != action:
                                continue

                            entries.append(entry)
                        except json.JSONDecodeError:
                            continue

            return entries[-limit:]

        except Exception as e:
            self.logger.error(f"加载成交历史失败：{e}")
            return []

    async def close_position(self, asset: str) -> bool:
        """
        Manually close a position via GUI.

        Args:
            asset: Asset symbol to close

        Returns:
            True if successful, False otherwise
        """
        if not self.bot_engine:
            self.logger.error("交易引擎尚未初始化，无法平仓")
            return False

        try:
            success = await self.bot_engine.close_position(asset)
            if success:
                self._add_event(f"Manually closed position: {asset}")
            return success
        except Exception as e:
            self.logger.error(f"平仓失败：{e}")
            return False

    def update_config(self, config: Dict):
        """
        Update bot configuration.

        Args:
            config: Dict with 'assets', 'interval', 'model' keys
        """
        if 'assets' in config:
            self.config['assets'] = config['assets']
        if 'interval' in config:
            self.config['interval'] = config['interval']
        if 'model' in config:
            self.config['model'] = config['model']

        self.logger.info(f"配置已更新：{self.config}")

    def get_assets(self) -> List[str]:
        """Get configured assets list"""
        if self.bot_engine:
            return self.bot_engine.get_assets()
        return self.config['assets']

    async def refresh_market_data(self) -> bool:
        """
        Manually refresh market data from OKX without starting the bot.
        Fetches account state, positions, and market data (prices, funding rates).
        Does NOT fetch TAAPI indicators or run AI analysis.

        Returns:
            True if successful, False otherwise
        """
        okx_api = None
        try:
            okx_api = OKXAPI()
            user_state = await okx_api.get_user_state()

            assets = self.get_assets()
            market_data = {}

            for asset in assets:
                try:
                    price = await okx_api.get_current_price(asset)
                    funding_rate = await okx_api.get_funding_rate(asset)
                    open_interest = await okx_api.get_open_interest(asset)

                    market_data[asset] = {
                        'price': price,
                        'funding_rate': funding_rate,
                        'open_interest': open_interest,
                        'timestamp': datetime.utcnow().isoformat(),
                        'intraday': {},  # Placeholder to avoid UI errors
                        'long_term': {}  # Placeholder to avoid UI errors
                    }
                except Exception as e:
                    self.logger.warning(f"刷新资产 {asset} 市场数据失败：{e}")
                    market_data[asset] = {
                        'price': None,
                        'funding_rate': None,
                        'open_interest': None,
                        'timestamp': datetime.utcnow().isoformat()
                    }

            if not self.bot_engine:
                state = BotState()
            else:
                state = self.bot_engine.get_state()

            state.balance = user_state.get('balance', state.balance)
            state.total_value = user_state.get('total_value', state.total_value)
            state.positions = user_state.get('positions', state.positions)
            state.market_data = market_data
            state.last_update = datetime.utcnow().isoformat()

            if self.state_manager:
                self.state_manager.update(state)

            self._add_event(f"📊 Market data refreshed - Balance: ${state.balance:,.2f}")
            self.logger.info("市场数据刷新成功")
            return True

        except Exception as e:
            self.logger.error(f"刷新市场数据失败：{e}", exc_info=True)
            self._add_event(f"❌ Refresh failed: {str(e)}", level="error")
            return False

        finally:
            if okx_api:
                try:
                    await okx_api.close()
                except Exception:
                    pass

    def approve_proposal(self, proposal_id: str) -> bool:
        """
        Approve and execute a trade proposal.

        Args:
            proposal_id: ID of the proposal to approve

        Returns:
            True if approval was sent (async execution), False if bot not running
        """
        if not self.bot_engine or not self.bot_engine.is_running:
            self.logger.error("交易引擎未运行，无法批准提案")
            return False

        try:
            # Schedule async execution
            asyncio.create_task(self.bot_engine.approve_proposal(proposal_id))
            self._add_event(f"✅ Proposal {proposal_id[:8]} approved - executing trade")
            self.logger.info(f"已批准提案：{proposal_id}")
            return True
        except Exception as e:
            self.logger.error(f"批准提案失败：{e}")
            self._add_event(f"❌ Approval failed: {str(e)}", level="error")
            return False

    def reject_proposal(self, proposal_id: str, reason: str = "User rejected") -> bool:
        """
        Reject a trade proposal.

        Args:
            proposal_id: ID of the proposal to reject
            reason: Reason for rejection (optional)

        Returns:
            True if rejection was sent (async execution), False if bot not running
        """
        if not self.bot_engine or not self.bot_engine.is_running:
            self.logger.error("交易引擎未运行，无法拒绝提案")
            return False

        try:
            # Schedule async execution
            asyncio.create_task(self.bot_engine.reject_proposal(proposal_id, reason))
            self._add_event(f"❌ Proposal {proposal_id[:8]} rejected - {reason}")
            self.logger.info(f"已拒绝提案：{proposal_id}，原因：{reason}")
            return True
        except Exception as e:
            self.logger.error(f"拒绝提案失败：{e}")
            self._add_event(f"❌ Rejection failed: {str(e)}", level="error")
            return False

    def get_pending_proposals(self) -> List[Dict]:
        """
        Get list of pending trade proposals.

        Returns:
            List of proposal dicts, or empty list if bot not running
        """
        if not self.bot_engine:
            return []

        try:
            proposals = self.bot_engine.get_pending_proposals()
            # Convert TradeProposal objects to dicts for JSON serialization
            return [
                {
                    'id': p.id,
                    'asset': p.asset,
                    'action': p.action,
                    'entry_price': p.entry_price,
                    'tp_price': p.tp_price,
                    'sl_price': p.sl_price,
                    'amount': p.amount,
                    'confidence': p.confidence,
                    'risk_reward_ratio': p.risk_reward_ratio,
                    'status': p.status,
                    'rationale': p.rationale,
                    'created_at': p.created_at.isoformat() if p.created_at else None
                }
                for p in proposals
            ]
        except Exception as e:
            self.logger.error(f"获取待处理提案列表失败：{e}")
            return []

    # ===== Callback Handlers =====

    def _on_state_update(self, state: BotState):
        """
        Callback when bot state updates.
        Updates state manager and tracks equity history.
        """
        if self.state_manager:
            self.state_manager.update(state)

        # Track equity history for charting
        self.equity_history.append({
            'time': state.last_update or datetime.utcnow().isoformat(),
            'value': state.total_value
        })

        # Keep only last 500 points
        if len(self.equity_history) > 500:
            self.equity_history = self.equity_history[-500:]

    def _on_trade_executed(self, trade: Dict):
        """
        Callback when trade is executed.
        Adds event to activity feed.
        """
        asset = trade.get('asset', '')
        action = trade.get('action', '').upper()
        amount = trade.get('amount', 0)
        price = trade.get('price', 0)

        message = f"{action} {amount:.6f} {asset} @ ${price:,.2f}"
        self._add_event(message)

    def _on_error(self, error: str):
        """
        Callback when error occurs.
        Adds error to activity feed.
        """
        self._add_event(f"ERROR: {error}", level="error")

    def _add_event(self, message: str, level: str = "info"):
        """Add event to recent events feed"""
        self.recent_events.append({
            'time': datetime.utcnow().strftime("%H:%M:%S"),
            'message': message,
            'level': level
        })

        # Keep only last 200 events
        if len(self.recent_events) > 200:
            self.recent_events = self.recent_events[-200:]

    # ===== Configuration Management =====

    async def update_config(self, config_updates: Dict) -> bool:
        """Update bot configuration and save to file"""
        try:
            # Save to .env-like configuration
            for key, value in config_updates.items():
                if isinstance(value, list):
                    CONFIG[key] = ' '.join(value)
                else:
                    CONFIG[key] = value

            # Also save to data/config.json for persistence
            self._save_config_file()

            self.logger.info(f"配置字段已更新：{list(config_updates.keys())}")
            return True
        except Exception as e:
            self.logger.error(f"更新配置失败：{e}")
            return False

    async def get_current_config(self) -> Dict:
        """Get current configuration"""
        try:
            # Load from CONFIG dict
            return {
                'assets': CONFIG.get('assets', 'BTC ETH').split(),
                'interval': CONFIG.get('interval', '5m'),
                'llm_model': CONFIG.get('llm_model', 'x-ai/grok-4'),
                'taapi_key': CONFIG.get('taapi_api_key', ''),
                'hyperliquid_private_key': CONFIG.get('hyperliquid_private_key', ''),
                'llm_api_key': CONFIG.get('llm_api_key', ''),
                'llm_base_url': CONFIG.get('llm_base_url', ''),
                'max_position_size': CONFIG.get('max_position_size', 1000),
                'max_leverage': CONFIG.get('max_leverage', 5),
                'desktop_notifications': CONFIG.get('desktop_notifications', True),
                'telegram_notifications': CONFIG.get('telegram_notifications', False),
                'telegram_token': CONFIG.get('telegram_token', ''),
                'telegram_chat_id': CONFIG.get('telegram_chat_id', ''),
            }
        except Exception as e:
            self.logger.error(f"读取当前配置失败：{e}")
            return {}

    def _save_config_file(self):
        """Save configuration to data/config.json"""
        try:
            config_path = Path('data/config.json')
            config_path.parent.mkdir(parents=True, exist_ok=True)

            config_data = {
                'strategy': {
                    'assets': CONFIG.get('assets', 'BTC ETH'),
                    'interval': CONFIG.get('interval', '5m'),
                    'llm_model': CONFIG.get('llm_model', 'x-ai/grok-4'),
                },
                'api_keys': {
                    'taapi_api_key': CONFIG.get('taapi_api_key', ''),
                    'hyperliquid_private_key': CONFIG.get('hyperliquid_private_key', ''),
                    'llm_api_key': CONFIG.get('llm_api_key', ''),
                    'llm_base_url': CONFIG.get('llm_base_url', ''),
                },
                'risk_management': {
                    'max_position_size': CONFIG.get('max_position_size', 1000),
                    'max_leverage': CONFIG.get('max_leverage', 5),
                },
                'notifications': {
                    'desktop_enabled': CONFIG.get('desktop_notifications', True),
                    'telegram_enabled': CONFIG.get('telegram_notifications', False),
                    'telegram_token': CONFIG.get('telegram_token', ''),
                    'telegram_chat_id': CONFIG.get('telegram_chat_id', ''),
                }
            }

            with open(config_path, 'w') as f:
                json.dump(config_data, f, indent=2)

            self.logger.debug(f"配置已保存到 {config_path}")
        except Exception as e:
            self.logger.error(f"保存配置文件失败：{e}")

    def _load_config_file(self):
        """Load configuration from data/config.json"""
        try:
            config_path = Path('data/config.json')
            if config_path.exists():
                with open(config_path, 'r') as f:
                    data = json.load(f)

                # Load strategy config
                if 'strategy' in data:
                    if 'assets' in data['strategy']:
                        CONFIG['assets'] = data['strategy']['assets']
                    if 'interval' in data['strategy']:
                        CONFIG['interval'] = data['strategy']['interval']
                    if 'llm_model' in data['strategy']:
                        CONFIG['llm_model'] = data['strategy']['llm_model']

                # Load API keys
                if 'api_keys' in data:
                    if 'taapi_api_key' in data['api_keys']:
                        CONFIG['taapi_api_key'] = data['api_keys']['taapi_api_key']
                    if 'hyperliquid_private_key' in data['api_keys']:
                        CONFIG['hyperliquid_private_key'] = data['api_keys']['hyperliquid_private_key']
                    if 'llm_api_key' in data['api_keys']:
                        CONFIG['llm_api_key'] = data['api_keys']['llm_api_key']
                    if 'llm_base_url' in data['api_keys']:
                         CONFIG['llm_base_url'] = data['api_keys']['llm_base_url']

                # Load risk management
                if 'risk_management' in data:
                    if 'max_position_size' in data['risk_management']:
                        CONFIG['max_position_size'] = data['risk_management']['max_position_size']
                    if 'max_leverage' in data['risk_management']:
                        CONFIG['max_leverage'] = data['risk_management']['max_leverage']

                # Load notifications
                if 'notifications' in data:
                    if 'desktop_enabled' in data['notifications']:
                        CONFIG['desktop_notifications'] = data['notifications']['desktop_enabled']
                    if 'telegram_enabled' in data['notifications']:
                        CONFIG['telegram_notifications'] = data['notifications']['telegram_enabled']
                    if 'telegram_token' in data['notifications']:
                        CONFIG['telegram_token'] = data['notifications']['telegram_token']
                    if 'telegram_chat_id' in data['notifications']:
                        CONFIG['telegram_chat_id'] = data['notifications']['telegram_chat_id']

                self.logger.debug(f"已从 {config_path} 读取配置")
        except Exception as e:
            self.logger.error(f"加载配置文件失败：{e}")

    async def test_api_connections(self) -> Dict[str, bool]:
        """Test API connections to all services"""
        results = {
            'taapi': False,
            'okx': False,
            'llm': False,
        }

        try:
            # Test TAAPI
            taapi_key = CONFIG.get('taapi_api_key', '')
            if taapi_key and taapi_key != 'your_taapi_key_here':
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.get(
                            f'https://api.taapi.io/ema?secret={taapi_key}&exchange=binance&symbol=BTC/USDT&interval=4h&period=14',
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as resp:
                            if resp.status == 200:
                                results['taapi'] = True
                    except Exception as e:
                        self.logger.debug(f"TAAPI 连通性测试失败：{e}")

            # Test OKX
            okx_client = None
            try:
                okx_client = OKXAPI()
                assets = self.get_assets()
                symbol_asset = assets[0] if assets else 'BTC'
                await okx_client.get_current_price(symbol_asset)
                results['okx'] = True
            except Exception as e:
                self.logger.debug(f"OKX 连通性测试失败：{e}")
            finally:
                if okx_client:
                    try:
                        await okx_client.close()
                    except Exception:
                        pass

            # Test LLM (AIHubMix)
            llm_key = CONFIG.get('llm_api_key', '')
            if llm_key and llm_key != 'your_llm_api_key_here':
                try:
                    from src.backend.agent.decision_maker import TradingAgent
                    agent = TradingAgent()
                    if agent.api_key:
                        results['llm'] = True
                except Exception as e:
                    self.logger.debug(f"LLM 连通性测试失败：{e}")
 
        except Exception as e:
            self.logger.error(f"测试 API 连通性时出错：{e}")

        return results
