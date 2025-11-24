import os
import sys
import time
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
import argparse

# Add project root to sys.path to allow imports from other modules
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from jafar.utils.topstepx_api_client import TopstepXClient
from jafar.cli.muxlisa_voice_output_handler import speak_muxlisa_text
from jafar.cli.telegram_handler import send_long_telegram_message

# --- Agent Configuration ---
LOGS_DIR = project_root / "logs" / "trade_agents"
LOGS_DIR.mkdir(exist_ok=True)

# State Transition Intervals (in seconds)
STATE_CHECK_INTERVAL_PENDING = 20  # How often to check if the order is filled
STATE_CHECK_INTERVAL_ACTIVE = 60   # How often to check the active position (1-min candles)

# Proximity Alert Configuration
PRICE_PROXIMITY_TICKS = 15 # Ticks away from SL/TP to trigger an alert

class TradeEscortAgent:
    """
    An intelligent agent to monitor the lifecycle of a single TopstepX order.
    States:
    - PENDING: Waiting for the initial order to be filled.
    - ACTIVE: The order has been filled, and an open position is being monitored.
    - COMPLETED: The position has been closed, and the agent's work is done.
    """

    def __init__(self, order_id: int, account_id: int, contract_id: str, expected_side: str):
        self.order_id = order_id
        self.account_id = account_id
        self.contract_id = contract_id
        self.expected_side = expected_side.upper() # BUY or SELL

        self.state = "PENDING"
        self.client = self._initialize_client()
        self.logger = self._setup_logger()
        
        # Position details, populated once ACTIVE
        self.position = None
        self.stop_loss = None
        self.take_profit = None
        self.tick_size = 0.1 # Default, will be updated

    def _setup_logger(self) -> logging.Logger:
        """Sets up a dedicated logger for this agent instance."""
        logger = logging.getLogger(f"TradeEscortAgent_{self.order_id}")
        logger.setLevel(logging.INFO)
        log_file = LOGS_DIR / f"{self.order_id}.log"
        handler = logging.FileHandler(log_file, mode='w')
        formatter = logging.Formatter('[%(asctime)s] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        # Also log to console for real-time visibility
        logger.addHandler(logging.StreamHandler(sys.stdout))
        return logger

    def _initialize_client(self) -> TopstepXClient:
        """Initializes and authenticates the TopstepX client."""
        client = TopstepXClient()
        if not client.is_authenticated:
            self.logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось аутентифицироваться в TopstepX API. Агент останавливается.")
            sys.exit(1) # Exit if we can't connect
        return client

    def run(self):
        """The main loop of the agent, driven by the state machine."""
        self.logger.info(f"Агент запущен. Цель: Ордер #{self.order_id} ({self.expected_side} {self.contract_id}). Состояние: {self.state}.")
        try:
            while self.state != "COMPLETED":
                if self.state == "PENDING":
                    self.handle_pending_state()
                    time.sleep(STATE_CHECK_INTERVAL_PENDING)
                elif self.state == "ACTIVE":
                    self.handle_active_state()
                    time.sleep(STATE_CHECK_INTERVAL_ACTIVE)
        except Exception as e:
            self.logger.error(f"В главном цикле агента произошла критическая ошибка: {e}", exc_info=True)
            send_long_telegram_message(f"🚨 **КРИТИЧЕСКАЯ ОШИБКА АГЕНТА**\nОрдер: #{self.order_id}\nОшибка: {e}")
        finally:
            self.logger.info("Работа агента завершена.")

    def handle_pending_state(self):
        """Checks if the tracked order has been filled."""
        self.logger.info("Проверка статуса ордера...")
        try:
            # A simple way to check for a fill is to see if an open position now exists
            positions = self.client.get_open_positions(self.account_id)
            for pos in positions.get("positions", []):
                if pos.get("contractId") == self.contract_id:
                    self.position = pos
                    self.transition_to_active()
                    return
            self.logger.info("Ордер все еще в ожидании (позиция не найдена).")
        except Exception as e:
            self.logger.warning(f"Ошибка при проверке статуса ордера: {e}")

    def transition_to_active(self):
        """Handles the transition from PENDING to ACTIVE."""
        self.state = "ACTIVE"
        self.logger.info("ОБНАРУЖЕНО ИСПОЛНЕНИЕ ОРДЕРА! Позиция открыта.")
        
        # Fetch SL/TP orders associated with the new position
        try:
            orders = self.client.get_working_orders(self.account_id)
            for order in orders.get("orders", []):
                if order.get("contractId") == self.contract_id:
                    if order.get("type") == 3: # Stop Loss
                        self.stop_loss = order.get("stopPrice")
                    elif order.get("type") == 2: # Take Profit (usually a Limit order)
                        self.take_profit = order.get("limitPrice")
            
            # Get tick size for proximity calculations
            contract_info = self.client.search_contract(self.contract_id)
            if contract_info and contract_info['contracts']:
                self.tick_size = contract_info['contracts'][0].get('tickSize', 0.1)

            self.logger.info(f"Позиция активна. SL: {self.stop_loss}, TP: {self.take_profit}, Tick Size: {self.tick_size}")

        except Exception as e:
            self.logger.error(f"Не удалось получить детали SL/TP для активной позиции: {e}")

        # Send notifications
        speak_muxlisa_text("Позиция очилди!")
        send_long_telegram_message(
            f"✅ **ИСПОЛНЕН ОРДЕР #{self.order_id}**\n\n"
            f"Открыта **{self.expected_side}** позиция по **{self.contract_id}**.\n"
            f"Агент Jafar переходит в режим активного сопровождения."
        )
        self.logger.info("Уведомления об открытии отправлены. Состояние изменено на ACTIVE.")

    def handle_active_state(self):
        """Monitors the open position, checking candles and proximity to SL/TP."""
        self.logger.info("Проверка статуса активной позиции (анализ 1-мин свечи)...")
        try:
            # First, check if the position still exists
            positions = self.client.get_open_positions(self.account_id)
            if not any(p.get("contractId") == self.contract_id for p in positions.get("positions", [])):
                self.transition_to_completed()
                return

            # Fetch the last closed 1-minute bar
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=1)
            bars_data = self.client.get_historical_bars(self.contract_id, start_time, end_time, unit_number=1, unit=2, limit=1)
            
            if not bars_data or not bars_data.get("bars"):
                self.logger.warning("Не удалось получить данные по последней свече.")
                return
            
            last_candle = bars_data["bars"][0]
            close_price = last_candle.get("c")
            self.logger.info(f"Последняя 1-мин свеча. Close: {close_price}, O: {last_candle.get('o')}, H: {last_candle.get('h')}, L: {last_candle.get('l')}")

            # Tactical Monitoring
            self.check_price_proximity(close_price)
            # self.analyze_candle_patterns(last_candle) # Placeholder for future logic

        except Exception as e:
            self.logger.warning(f"Ошибка при обработке активного состояния: {e}")

    def check_price_proximity(self, current_price: float):
        """Checks if the current price is close to SL or TP and sends alerts."""
        if not current_price: return

        proximity_threshold = PRICE_PROXIMITY_TICKS * self.tick_size

        if self.stop_loss:
            if abs(current_price - self.stop_loss) <= proximity_threshold:
                self.logger.warning(f"ЦЕНА ({current_price}) ПРИБЛИЖАЕТСЯ К STOP-LOSS ({self.stop_loss})!")
                speak_muxlisa_text("Диққат! Нарх стоп-лоссга яқинлашмоқда!")
                send_long_telegram_message(f"⚠️ **{self.contract_id}**: Цена ({current_price}) приближается к Stop-Loss ({self.stop_loss})!")
        
        if self.take_profit:
            if abs(current_price - self.take_profit) <= proximity_threshold:
                self.logger.info(f"Цена ({current_price}) приближается к Take-Profit ({self.take_profit}).")
                send_long_telegram_message(f"ℹ️ **{self.contract_id}**: Цена ({current_price}) приближается к Take-Profit ({self.take_profit}).")

    def transition_to_completed(self):
        """Handles the final transition to the COMPLETED state."""
        self.state = "COMPLETED"
        self.logger.info("ОБНАРУЖЕНО ЗАКРЫТИЕ ПОЗИЦИИ!")
        speak_muxlisa_text("Савдо ёпилди!")
        send_long_telegram_message(
            f"🔵 **ПОЗИЦИЯ ЗАКРЫТА**\n\n"
            f"Позиция по ордеру #{self.order_id} ({self.contract_id}) была закрыта.\n"
            f"Результат доступен в вашем торговом терминале."
        )
        self.logger.info("Финальные уведомления отправлены. Состояние изменено на COMPLETED.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jafar Trade Escort Agent")
    parser.add_argument("--order-id", type=int, required=True, help="The TopstepX order ID to monitor.")
    parser.add_argument("--account-id", type=int, required=True, help="The TopstepX account ID.")
    parser.add_argument("--contract-id", type=str, required=True, help="The contract ID (e.g., CON.F.US.MGC.Z25).")
    parser.add_argument("--expected-side", type=str, required=True, choices=["BUY", "SELL"], help="The expected side of the trade.")
    
    args = parser.parse_args()

    agent = TradeEscortAgent(
        order_id=args.order_id,
        account_id=args.account_id,
        contract_id=args.contract_id,
        expected_side=args.expected_side.upper()
    )
    agent.run()