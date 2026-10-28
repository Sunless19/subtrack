"""Add / edit dialog for a single subscription.

Common fields are always shown; payment method, contract, pause and
introductory price live under "More options", which opens by itself when
the subscription uses any of them.
"""

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
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
    QToolButton,
    QWidget,
)

from subtrack.domain import templates
from subtrack.domain.models import BillingCycle, Category, Currency, PriceChange, Subscription


def _to_qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def _from_qdate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def _date_edit(value: date | None = None) -> QDateEdit:
    edit = QDateEdit(_to_qdate(value or date.today()))
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd MMM yyyy")
    return edit


def _optional(check: QCheckBox, *widgets) -> None:
    """Widgets are only enabled while the check box is ticked."""
    for widget in widgets:
        widget.setEnabled(check.isChecked())
        check.toggled.connect(widget.setEnabled)


def _row(*widgets, stretch_last: bool = True) -> QHBoxLayout:
    layout = QHBoxLayout()
    for i, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if stretch_last and i == len(widgets) - 1 else 0)
    return layout


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
    def __init__(
        self,
        parent=None,
        subscription: Subscription | None = None,
        price_history=(),
        payment_methods: list[str] = (),
    ):
        super().__init__(parent)
        self._original = subscription
        self.setWindowTitle("Edit subscription" if subscription else "Add subscription")
        self.setMinimumWidth(420)

        # ---- common fields -------------------------------------------------
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(100)
        self.name_edit.setPlaceholderText("e.g. Netflix — start typing for suggestions")
        completer = QCompleter(templates.names(), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.name_edit.setCompleter(completer)
        completer.activated.connect(self._apply_template)
        self.name_edit.editingFinished.connect(lambda: self._apply_template(self.name_edit.text()))

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0, 1_000_000)
        self.price_spin.setDecimals(2)

        self.currency_combo = QComboBox()
        for currency in Currency:
            self.currency_combo.addItem(currency.value, currency)

        self.cycle_combo = QComboBox()
        for cycle in BillingCycle:
            self.cycle_combo.addItem(cycle.label, cycle)
        self.cycle_combo.setCurrentIndex(self.cycle_combo.findData(BillingCycle.MONTHLY))

        self.category_combo = QComboBox()
        for category in Category:
            self.category_combo.addItem(category.label, category)

        self.first_payment_edit = _date_edit()

        self.trial_check = QCheckBox("Free trial until")
        self.trial_edit = _date_edit()
        _optional(self.trial_check, self.trial_edit)

        self.shared_spin = QSpinBox()
        self.shared_spin.setRange(1, 50)
        self.shared_spin.setSpecialValueText("Just me")
        self.shared_spin.setSuffix(" people")
        self.share_label = QLabel()
        self.share_label.setStyleSheet("color: gray;")
        for signal in (self.shared_spin.valueChanged, self.price_spin.valueChanged, self.currency_combo.currentIndexChanged):
            signal.connect(self._update_share_label)

        self.rarely_used_check = QCheckBox("I rarely use this")

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(54)

        self.history_label = QLabel(describe_price_history(list(price_history)))
        self.history_label.setStyleSheet("color: gray;")

        # ---- more options ------------------------------------------------------
        self.payment_method_combo = QComboBox()
        self.payment_method_combo.setEditable(True)
        self.payment_method_combo.addItems(["", *payment_methods])
        self.payment_method_combo.lineEdit().setPlaceholderText("e.g. Revolut card, PayPal")
        self.payment_method_combo.lineEdit().setMaxLength(60)

        self.contract_check = QCheckBox("Contract ends")
        self.contract_edit = _date_edit()
        self.notice_spin = QSpinBox()
        self.notice_spin.setRange(0, 365)
        self.notice_spin.setPrefix("cancel ")
        self.notice_spin.setSuffix(" days before")
        _optional(self.contract_check, self.contract_edit, self.notice_spin)

        self.pause_check = QCheckBox("Paused from")
        self.pause_from_edit = _date_edit()
        self.pause_until_edit = _date_edit()
        _optional(self.pause_check, self.pause_from_edit, self.pause_until_edit)

        self.promo_check = QCheckBox("Intro price")
        self.promo_spin = QDoubleSpinBox()
        self.promo_spin.setRange(0, 1_000_000)
        self.promo_spin.setDecimals(2)
        self.promo_until_edit = _date_edit()
        _optional(self.promo_check, self.promo_spin, self.promo_until_edit)

        self.more_widget = QWidget()
        more = QFormLayout(self.more_widget)
        more.setContentsMargins(0, 0, 0, 0)
        more.addRow("Paid with", self.payment_method_combo)
        more.addRow(self.contract_check, _row(self.contract_edit, self.notice_spin))
        more.addRow(self.pause_check, _row(self.pause_from_edit, QLabel("until"), self.pause_until_edit))
        more.addRow(self.promo_check, _row(self.promo_spin, QLabel("until"), self.promo_until_edit))

        self.more_button = QToolButton()
        self.more_button.setText("More options")
        self.more_button.setCheckable(True)
        self.more_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.more_button.setArrowType(Qt.RightArrow)
        self.more_button.setStyleSheet("QToolButton { border: none; }")
        self.more_button.toggled.connect(self._show_more)
        self.more_widget.setVisible(False)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow("Name", self.name_edit)
        form.addRow("Price", _row(self.price_spin, self.currency_combo, stretch_last=False))
        if price_history:
            form.addRow("Price changes", self.history_label)
        form.addRow("Split between", _row(self.shared_spin, self.share_label))
        form.addRow("Billing cycle", self.cycle_combo)
        form.addRow("Category", self.category_combo)
        form.addRow("First payment", self.first_payment_edit)
        form.addRow("", _row(self.trial_check, self.trial_edit))
        form.addRow("", self.rarely_used_check)
        form.addRow("Notes", self.notes_edit)
        form.addRow(self.more_button)
        form.addRow(self.more_widget)
        form.addRow(buttons)

        if subscription:
            self._load(subscription)
        self._update_share_label()

    def _show_more(self, show: bool) -> None:
        self.more_widget.setVisible(show)
        self.more_button.setArrowType(Qt.DownArrow if show else Qt.RightArrow)
        self.adjustSize()

    def _apply_template(self, name: str) -> None:
        """Typing a known service fills category and cycle, but only when adding and only once."""
        template = templates.find(name)
        if template is None or self._original is not None:
            return
        self.name_edit.setText(template.name)
        self.category_combo.setCurrentIndex(self.category_combo.findData(template.category))
        self.cycle_combo.setCurrentIndex(self.cycle_combo.findData(template.billing_cycle))

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

        self.payment_method_combo.setCurrentText(sub.payment_method)
        if sub.contract_end_date:
            self.contract_check.setChecked(True)
            self.contract_edit.setDate(_to_qdate(sub.contract_end_date))
            self.notice_spin.setValue(sub.notice_days)
        if sub.paused_from and sub.paused_until:
            self.pause_check.setChecked(True)
            self.pause_from_edit.setDate(_to_qdate(sub.paused_from))
            self.pause_until_edit.setDate(_to_qdate(sub.paused_until))
        if sub.promo_price is not None and sub.promo_until:
            self.promo_check.setChecked(True)
            self.promo_spin.setValue(float(sub.promo_price))
            self.promo_until_edit.setDate(_to_qdate(sub.promo_until))
        uses_more = bool(sub.payment_method) or sub.contract_end_date or sub.paused_from or sub.promo_price is not None
        self.more_button.setChecked(bool(uses_more))

    def subscription(self) -> Subscription:
        """The subscription as entered. Keeps the id and active flag when editing."""
        contract = self.contract_check.isChecked()
        paused = self.pause_check.isChecked()
        promo = self.promo_check.isChecked()
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
            payment_method=self.payment_method_combo.currentText(),
            contract_end_date=_from_qdate(self.contract_edit.date()) if contract else None,
            notice_days=self.notice_spin.value() if contract else 0,
            paused_from=_from_qdate(self.pause_from_edit.date()) if paused else None,
            paused_until=_from_qdate(self.pause_until_edit.date()) if paused else None,
            promo_price=Decimal(f"{self.promo_spin.value():.2f}") if promo else None,
            promo_until=_from_qdate(self.promo_until_edit.date()) if promo else None,
        )
