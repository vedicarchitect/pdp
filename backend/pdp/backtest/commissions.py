from dataclasses import dataclass
from decimal import Decimal

from pdp.settings import BacktestCommissionSettings


@dataclass
class CommissionBreakdown:
    brokerage: Decimal
    stt: Decimal
    txn_charge: Decimal
    sebi: Decimal
    stamp_duty: Decimal
    ipft: Decimal
    gst: Decimal
    total_inr: Decimal


class CommissionCalculator:
    def __init__(self, settings: BacktestCommissionSettings) -> None:
        self.settings = settings
        self.brokerage = settings.brokerage_per_order
        self.stt_rate = settings.stt_rate
        self.txn_charge_rate = settings.txn_charge_rate
        self.sebi_rate = settings.sebi_rate
        self.stamp_duty_rate = settings.stamp_duty_rate
        self.ipft_rate = getattr(settings, "ipft_rate", Decimal("0.000000001"))
        self.gst_rate = settings.gst_rate

    def calculate(self, side: str, turnover_inr: Decimal) -> CommissionBreakdown:
        if turnover_inr == 0:
            return CommissionBreakdown(
                brokerage=self.brokerage,
                stt=Decimal("0.0"),
                txn_charge=Decimal("0.0"),
                sebi=Decimal("0.0"),
                stamp_duty=Decimal("0.0"),
                ipft=Decimal("0.0"),
                gst=Decimal("0.0"),
                total_inr=self.brokerage,
            )

        side = side.lower()

        stt = Decimal("0.0")
        stamp_duty = Decimal("0.0")

        if side == "sell":
            stt = turnover_inr * self.stt_rate
        elif side == "buy":
            stamp_duty = turnover_inr * self.stamp_duty_rate

        txn_charge = turnover_inr * self.txn_charge_rate
        sebi = turnover_inr * self.sebi_rate
        ipft = turnover_inr * self.ipft_rate

        # GST base: brokerage + txn + SEBI turnover fee + IPFT (per Dhan schedule)
        gst = (self.brokerage + txn_charge + sebi + ipft) * self.gst_rate

        total_inr = self.brokerage + stt + txn_charge + sebi + stamp_duty + ipft + gst

        return CommissionBreakdown(
            brokerage=self.brokerage,
            stt=stt,
            txn_charge=txn_charge,
            sebi=sebi,
            stamp_duty=stamp_duty,
            ipft=ipft,
            gst=gst,
            total_inr=total_inr,
        )


class NullCommissionCalculator:
    def __init__(self, settings: BacktestCommissionSettings) -> None:
        pass

    def calculate(self, side: str, turnover_inr: Decimal) -> CommissionBreakdown:
        return CommissionBreakdown(
            brokerage=Decimal("0.0"),
            stt=Decimal("0.0"),
            txn_charge=Decimal("0.0"),
            sebi=Decimal("0.0"),
            stamp_duty=Decimal("0.0"),
            ipft=Decimal("0.0"),
            gst=Decimal("0.0"),
            total_inr=Decimal("0.0"),
        )
