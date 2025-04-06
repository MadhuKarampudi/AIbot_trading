import logging
from decimal import Decimal
from typing import Dict, List

from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.data_feed.candles_feed.candles_factory import CandlesFactory, CandlesConfig
from hummingbot.connector.connector_base import ConnectorBase

class AITradingBot(ScriptStrategyBase):
    bid_spread = 0.0001 
    ask_spread = 0.0001  
    order_refresh_time = 15 
    order_amount = 0.01 
    trading_pair = "ETH-USDT"
    exchange = "binance"
    price_source = PriceType.MidPrice 
    next_order_time = 0  
    candle_exchange = "binance"
    candle_interval = "1m"  
    candles_length = 30  
    max_records = 1000  
    candles = CandlesFactory.get_candle(CandlesConfig(
        connector=candle_exchange,
        trading_pair=trading_pair,
        interval=candle_interval,
        max_records=max_records
    ))
    markets = {exchange: {trading_pair}}

    def _init_(self, connectors: Dict[str, ConnectorBase]):
        super()._init_(connectors)
        self.candles.start()

    def on_stop(self):
        self.candles.stop()

    def on_tick(self):
        if self.next_order_time <= self.current_timestamp:
            self.cancel_all_orders()
            new_orders = self.create_trading_proposal()
            adjusted_orders = self.adjust_proposal_to_budget(new_orders)
            self.place_orders(adjusted_orders)
            self.next_order_time = self.current_timestamp + self.order_refresh_time

    def get_candles_with_features(self):
        candles_df = self.candles.candles_df
        candles_df.ta.rsi(length=self.candles_length, append=True)
        candles_df.ta.macd(append=True)
        candles_df.ta.bbands(append=True)
        candles_df.ta.natr(append=True)
        candles_df.ta.ha(append=True)
        return candles_df

    def create_trading_proposal(self) -> List[OrderCandidate]:
        ref_price = self.connectors[self.exchange].get_price_by_type(self.trading_pair, self.price_source)
        buy_price = ref_price * Decimal(1 - self.bid_spread)
        sell_price = ref_price * Decimal(1 + self.ask_spread)

        buy_order = OrderCandidate(
            trading_pair=self.trading_pair, 
            is_maker=True, 
            order_type=OrderType.LIMIT,
            order_side=TradeType.BUY, 
            amount=Decimal(self.order_amount), 
            price=buy_price
        )

        sell_order = OrderCandidate(
            trading_pair=self.trading_pair, 
            is_maker=True, 
            order_type=OrderType.LIMIT,
            order_side=TradeType.SELL, 
            amount=Decimal(self.order_amount), 
            price=sell_price
        )

        return [buy_order, sell_order]

    def adjust_proposal_to_budget(self, proposal: List[OrderCandidate]) -> List[OrderCandidate]:
        return self.connectors[self.exchange].budget_checker.adjust_candidates(proposal, all_or_none=True)

    def place_orders(self, orders: List[OrderCandidate]) -> None:
        for order in orders:
            self.place_order(self.exchange, order)

    def place_order(self, connector_name: str, order: OrderCandidate):
        if order.order_side == TradeType.SELL:
            self.sell(connector_name=connector_name, trading_pair=order.trading_pair, amount=order.amount,
                      order_type=order.order_type, price=order.price)
        else:
            self.buy(connector_name=connector_name, trading_pair=order.trading_pair, amount=order.amount,
                     order_type=order.order_type, price=order.price)

    def cancel_all_orders(self):
        for order in self.get_active_orders(connector_name=self.exchange):
            self.cancel(self.exchange, order.trading_pair, order.client_order_id)

    def did_fill_order(self, event: OrderFilledEvent):
        message = f"{event.trade_type.name} {round(event.amount, 2)} {event.trading_pair} on {self.exchange} at {round(event.price, 2)}"
        self.log_with_clock(logging.INFO, message)
        self.notify_hb_app_with_timestamp(message)

    def format_status(self) -> str:
        if not self.ready_to_trade:
            return "Market connectors are not ready."

        lines = ["\nBot Status:\n"]

        balance_df = self.get_balance_df()
        lines.append("Balances:")
        lines.extend(balance_df.to_string(index=False).split("\n"))

        try:
            orders_df = self.active_orders_df()
            lines.append("\nActive Orders:")
            lines.extend(orders_df.to_string(index=False).split("\n"))
        except ValueError:
            lines.append("\nNo active maker orders.")

        candles_df = self.get_candles_with_features()
        lines.append(f"\nCandlestick Data ({self.candle_interval} interval):")
        lines.extend(candles_df.tail(self.candles_length).iloc[::-1].to_string(index=False).split("\n"))

        return "\n".join(lines)