"""Dashboard tab: totals, spending per category and over time, and upcoming payments."""

from datetime import date

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSet,
    QChart,
    QChartView,
    QPieSeries,
    QStackedBarSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from subtrack.services.currency_service import CurrencyService
from subtrack.services.stats_service import StatsService
from subtrack.ui.badge import badge_icon

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

        # Spending per month: the last 12 months, then a 12-month forecast. Built once;
        # refresh() only replaces the data (re-adding axes each time would stack them).
        self.history_chart = QChart()
        self.history_chart.setTitle("Spending per month — last 12 months and forecast")
        self.history_chart.legend().setAlignment(Qt.AlignBottom)
        self.history_chart.setAnimationOptions(QChart.NoAnimation)
        self.history_series = QStackedBarSeries()
        self.history_chart.addSeries(self.history_series)
        self.history_x = QBarCategoryAxis()
        self.history_x.setLabelsAngle(-90)  # 24 months only fit side by side when vertical
        self.history_x.setTruncateLabels(False)  # Qt would otherwise shrink them to "…"
        small = self.history_x.labelsFont()
        small.setPointSizeF(max(small.pointSizeF() - 1.5, 7))
        self.history_x.setLabelsFont(small)
        self.history_y = QValueAxis()
        self.history_chart.addAxis(self.history_x, Qt.AlignBottom)
        self.history_chart.addAxis(self.history_y, Qt.AlignLeft)
        self.history_series.attachAxis(self.history_x)
        self.history_series.attachAxis(self.history_y)
        self.history_view = QChartView(self.history_chart)
        self.history_view.setRenderHint(QPainter.Antialiasing)

        if self.palette().window().color().lightness() < 128:  # follow Windows dark mode
            for c in (chart, self.history_chart):
                c.setTheme(QChart.ChartThemeDark)
                c.setBackgroundRoundness(0)

        self.chart_tabs = QTabWidget()
        self.chart_tabs.addTab(self.chart_view, "By category")
        self.chart_tabs.addTab(self.history_view, "Over time")

        self.upcoming_table = QTableWidget(0, 3)
        self.upcoming_table.setHorizontalHeaderLabels(["Date", "Subscription", "Amount"])
        self.upcoming_table.verticalHeader().hide()
        self.upcoming_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.upcoming_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.upcoming_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        upcoming_box = QGroupBox(f"Upcoming payments ({UPCOMING_DAYS} days)")
        QVBoxLayout(upcoming_box).addWidget(self.upcoming_table)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self.chart_tabs, 1)
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
            name = QTableWidgetItem(payment.subscription.name)
            name.setIcon(badge_icon(payment.subscription.name))
            self.upcoming_table.setItem(row, 0, QTableWidgetItem(payment.due_date.strftime("%a %d %b")))
            self.upcoming_table.setItem(row, 1, name)
            self.upcoming_table.setItem(row, 2, amount)

        self._refresh_history(base)

    def _refresh_history(self, base: str) -> None:
        """Stacked bars so past months and forecast months get different colours."""
        months = self._stats.monthly_spending()
        spent, forecast = QBarSet("Spent (estimated)"), QBarSet("Forecast")
        spent.setColor(QColor("#1e88e5"))
        forecast.setColor(QColor("#90caf9"))
        for month in months:
            value = float(month.amount)
            spent.append(0 if month.is_forecast else value)
            forecast.append(value if month.is_forecast else 0)
        self.history_series.clear()
        self.history_series.append(spent)
        self.history_series.append(forecast)

        # Category labels must be unique, so every month carries its year ("Nov 25", "Nov 26").
        self.history_x.clear()
        self.history_x.append([m.month.strftime("%b %y") for m in months])
        top = max((float(m.amount) for m in months), default=0)
        self.history_y.setRange(0, top * 1.1 if top else 1)
        self.history_y.applyNiceNumbers()
        self.history_y.setLabelFormat(f"%.0f {base}")
