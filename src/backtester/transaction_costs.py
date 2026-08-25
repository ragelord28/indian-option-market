from dataclasses import dataclass

@dataclass
class NSETransactionCostModel:
    """
    Centralized cost configuration class applying NSE F&O statutory charges.
    """
    brokerage_per_order: float = 20.0
    stt_sell_options_pct: float = 0.001     # 0.1%
    exchange_turnover_pct: float = 0.0005   # 0.05%
    gst_pct: float = 0.18                   # 18%
    sebi_charges_pct: float = 0.0           # excluded in tests
    stamp_duty_buy_pct: float = 0.00003     # 0.003%
    slippage_pct: float = 0.0               # excluded in tests

    def calculate_costs(
        self,
        entry_price: float,
        exit_price: float,
        quantity: int,
        is_option: bool = True
    ) -> float:
        """
        Calculate total transaction costs for a round-trip trade (buy and sell).
        Includes brokerage, STT, Exchange charges, GST, SEBI, Stamp duty, and slippage.
        """
        if not is_option:
            # Fallback for equity/futures can be added here, currently defaulting to same structure
            pass

        entry_turnover = entry_price * quantity
        exit_turnover = exit_price * quantity
        total_turnover = entry_turnover + exit_turnover

        brokerage = self.brokerage_per_order * 2  # Entry and Exit
        stt = exit_turnover * self.stt_sell_options_pct
        exchange_txn = total_turnover * self.exchange_turnover_pct
        sebi = total_turnover * self.sebi_charges_pct
        gst = (brokerage + exchange_txn + sebi) * self.gst_pct
        stamp_duty = entry_turnover * self.stamp_duty_buy_pct
        
        slippage = total_turnover * self.slippage_pct

        total_costs = brokerage + stt + exchange_txn + gst + sebi + stamp_duty + slippage
        return round(total_costs, 2)
