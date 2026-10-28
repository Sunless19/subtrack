"""Add / edit dialog for a single subscription."""

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
)

from subtrack.domain.models import BillingCycle, Category, Currency, PriceChange, Subscription


def _to_qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def _from_qdate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def describe_price_history(history: list[PriceChange]) -> str:
    """e.g. '12 Mar 2026: 39.99 → 49.99 RON (+25.0%)', one line per change, newest first."""
    lines = []
    for change in reversed(history):
        old = f"{change.old_price:.2f}" + ("" if change.old_currency is change.new_currency else f" {change.old_currency.value}")
        line = f"{change.changed_on:%d %b %Y}: {old} → {change.new_price:.2f} {change.new_currency.value}"
        if change.old_currency is change.new_currency and change.old_price:
            percent = (change.new_price - change.old_price) / change.old_price * 100
            line += f" ({percent:+.1f}%)"
        lines.append(line)
    return "\n".join(lines)


class SubscriptionDialog(QDialog):
    def __init__(self, parent=None, subscription: Subscription | None = None, price_history=()):
        super().__init__(parent)
        self._original = subscription
        self.setWindowTitle("Edit subscription" if subscription else "Add subscription")
        self.setMinimumWidth(380)

        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(100)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0, 1_000_000)
        self.price_spin.setDecimals(2)

        self.currency_combo = QComboBox()
        for currency in Currency:
            self.currency_combo.addItem(currency.value, currency)

        price_row = QHBoxLayout()
        price_row.addWidget(self.price_spin, 1)
        price_row.addWidget(self.currency_combo)

        self.cycle_combo = QComboBox()
        for cycle in BillingCycle:
            self.cycle_combo.addItem(cycle.label, cycle)
        self.cycle_combo.setCurrentIndex(self.cycle_combo.findData(BillingCycle.MONTHLY))

        self.category_combo = QComboBox()
        for category in Category:
            self.category_combo.addItem(category.label, category)

        self.first_payment_edit = QDateEdit(_to_qdate(date.today()))
        self.first_payment_edit.setCalendarPopup(True)
        self.first_payment_edit.setDisplayFormat("dd MMM yyyy")

        self.trial_check = QCheckBox("Free trial until")
        self.trial_edit = QDateEdit(_to_qdate(date.today()))
        self.trial_edit.setCalendarPopup(True)
        self.trial_edit.setDisplayFormat("dd MMM yyyy")
        self.trial_edit.setEnabled(False)
        self.trial_check.toggled.connect(self.trial_edit.setEnabled)

        trial_row = QHBoxLayout()
        trial_row.addWidget(self.trial_check)
        trial_row.addWidget(self.trial_edit, 1)

        self.shared_spin = QSpinBox()
        self.shared_spin.setRange(1, 50)
        self.shared_spin.setSpecialValueText("Just me")
        self.shared_spin.setSuffix(" people")
        self.share_label = QLabel()
        self.share_label.setStyleSheet("color: gray;")
        shared_row = QHBoxLayout()
        shared_row.addWidget(self.shared_spin)
        shared_row.addWidget(self.share_label, 1)
        for signal in (self.shared_spin.valueChanged, self.price_spin.valueChanged, self.currency_combo.currentIndexChanged):
            signal.connect(self._update_share_label)

        self.rarely_used_check = QCheckBox("I rarely use this")

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(60)

        self.history_label = QLabel(describe_price_history(list(price_history)))
        self.history_label.setStyleSheet("color: gray;")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow("Name", self.name_edit)
        form.addRow("Price", price_row)
        if price_history:
            form.addRow("Price changes", self.history_label)
        form.addRow("Split between", shared_row)
        form.addRow("Billing cycle", self.cycle_combo)
        form.addRow("Category", self.category_combo)
        form.addRow("First payment", self.first_payment_edit)
        form.addRow("", trial_row)
        form.addRow("", self.rarely_used_check)
        form.addRow("Notes", self.notes_edit)
        form.addRow(buttons)

        if subscription:
            self._load(subscription)
        self._update_share_label()

    def _update_share_label(self) -> None:
        people = self.shared_spin.value()
        if people == 1:
            self.share_label.setText("")
            return
        share = Decimal(f"{self.price_spin.value():.2f}") / people
        self.share_label.setText(f"your share: {share:.2f} {self.currency_combo.currentText()} per payment")

    def _load(self, sub: Subscription) -> None:
        self.name_edit.setText(sub.name)
        self.price_spin.setValue(float(sub.price))
        self.currency_combo.setCurrentIndex(self.currency_combo.findData(sub.currency))
        self.cycle_combo.setCurrentIndex(self.cycle_combo.findData(sub.billing_cycle))
        self.category_combo.setCurrentIndex(self.category_combo.findData(sub.category))
        self.first_payment_edit.setDate(_to_qdate(sub.first_payment_date))
        if sub.trial_end_date:
            self.trial_check.setChecked(True)
            self.trial_edit.setDate(_to_qdate(sub.trial_end_date))
        self.rarely_used_check.setChecked(sub.rarely_used)
        self.notes_edit.setPlainText(sub.notes)
        self.shared_spin.setValue(sub.shared_with)

    def subscription(self) -> Subscription:
        """The subscription as entered. Keeps the id and active flag when editing."""
        return Subscription(
            id=self._original.id if self._original else None,
            active=self._original.active if self._original else True,
            name=self.name_edit.text(),
            # Go through str so 9.99 does not become Decimal('9.9900000000000002131...')
            price=Decimal(f"{self.price_spin.value():.2f}"),
            # Qt hands str-based enums back as plain str, so convert them again.
            currency=Currency(self.currency_combo.currentData()),
            billing_cycle=BillingCycle(self.cycle_combo.currentData()),
            category=Category(self.category_combo.currentData()),
            first_payment_date=_from_qdate(self.first_payment_edit.date()),
            trial_end_date=_from_qdate(self.trial_edit.date()) if self.trial_check.isChecked() else None,
            rarely_used=self.rarely_used_check.isChecked(),
            notes=self.notes_edit.toPlainText(),
            shared_with=self.shared_spin.value(),
        )
