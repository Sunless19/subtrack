"""Dashboard tab: totals, spending per category and upcoming payments."""

from datetime import date

from PySide6.QtCharts import QChart, QChartView, QPieSeries
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from subtrack.services.currency_service import CurrencyService
from subtrack.services.stats_service import StatsService

UPCOMING_DAYS = 30


def _stat_box(title: str) -> tuple[QGroupBox, QLabel]:
    box = QGroupBox(title)
    value = QLabel("-")
    value.setStyleSheet("font-size: 22px; font-weight: 600;")
    value.setAlignment(Qt.AlignCenter)
    QVBoxLayout(box).addWidget(value)
    return box, value


class DashboardView(QWidget):
    def __init__(self, stats: StatsService, currency: CurrencyService, today=date.today, parent=None):
        super().__init__(parent)
        self._stats = stats
        self._currency = currency
        self._today = today

        monthly_box, self.monthly_value = _stat_box("Per month")
        yearly_box, self.yearly_value = _stat_box("Per year")
        count_box, self.upcoming_value = _stat_box(f"Due in next {UPCOMING_DAYS} days")
        totals_row = QHBoxLayout()
        for box in (monthly_box, yearly_box, count_box):
            totals_row.addWidget(box)

        self.pie = QPieSeries()
        chart = QChart()
        chart.addSeries(self.pie)
        chart.setTitle("Monthly cost per category")
        chart.legend().setAlignment(Qt.AlignRight)
        chart.setAnimationOptions(QChart.NoAnimation)
        self.chart_view = QChartView(chart)
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        self.chart_view.setMinimumWidth(360)

        self.upcoming_table = QTableWidget(0, 3)
        self.upcoming_table.setHorizontalHeaderLabels(["Date", "Subscription", "Amount"])
        self.upcoming_table.verticalHeader().hide()
        self.upcoming_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.upcoming_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.upcoming_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        upcoming_box = QGroupBox(f"Upcoming payments ({UPCOMING_DAYS} days)")
        QVBoxLayout(upcoming_box).addWidget(self.upcoming_table)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self.chart_view, 1)
        bottom_row.addWidget(upcoming_box, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(totals_row)
        layout.addLayout(bottom_row, 1)

        self.refresh()

    def refresh(self) -> None:
        base = self._currency.base_currency().value
        upcoming = self._stats.upcoming_payments(self._today(), UPCOMING_DAYS)

        self.monthly_value.setText(f"{self._stats.monthly_total():.2f} {base}")
        self.yearly_value.setText(f"{self._stats.yearly_total():.2f} {base}")
        self.upcoming_value.setText(f"{sum(p.amount_in_base for p in upcoming):.2f} {base}")

        self.pie.clear()
        for category, amount in self._stats.monthly_total_by_category().items():
            if amount > 0:
                pie_slice = self.pie.append(f"{category.label} ({amount:.2f})", float(amount))
                pie_slice.setLabelVisible(len(self.pie.slices()) <= 6)

        self.upcoming_table.setRowCount(len(upcoming))
        for row, payment in enumerate(upcoming):
            amount = QTableWidgetItem(f"{payment.amount_in_base:.2f} {base}")
            amount.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.upcoming_table.setItem(row, 0, QTableWidgetItem(payment.due_date.strftime("%a %d %b")))
            self.upcoming_table.setItem(row, 1, QTableWidgetItem(payment.subscription.name))
            self.upcoming_table.setItem(row, 2, amount)
