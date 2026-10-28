"""Reminders tab: every payment and trial end from 30 days ago to 30 days ahead.

Shows whether each was paid, reminded, snoozed or is still coming, so a missed
notification is never lost. Payments can be marked as paid (or unmarked) here.
"""

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from subtrack.services.reminder_service import ReminderService, TimelineEntry, TimelineStatus

_STATUS_COLOURS = {
    TimelineStatus.PAID: "#2e7d32",
    TimelineStatus.NOT_MARKED_PAID: "#c62828",
    TimelineStatus.DUE_TODAY: "#e65100",
    TimelineStatus.SNOOZED: "#6a1b9a",
}


class RemindersView(QWidget):
    changed = Signal()  # something was marked paid / unpaid

    def __init__(self, reminders: ReminderService, now=datetime.now, parent=None):
        super().__init__(parent)
        self._reminders = reminders
        self._now = now
        self._entries: list[TimelineEntry] = []

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Date", "Subscription", "What", "Amount", "Status"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(self._toggle_paid)

        self.paid_button = QPushButton("Mark as paid")
        self.paid_button.clicked.connect(self.mark_selected_paid)
        self.unpaid_button = QPushButton("Undo paid")
        self.unpaid_button.clicked.connect(self.unmark_selected_paid)
        hint = QLabel("Last 30 days and next 30 days. Double-click a payment to mark it paid.")
        hint.setStyleSheet("color: gray;")

        buttons = QHBoxLayout()
        buttons.addWidget(hint, 1)
        buttons.addWidget(self.paid_button)
        buttons.addWidget(self.unpaid_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

        self.refresh()

    def refresh(self) -> None:
        now = self._now()
        today = now.date()
        selected = self.selected_entry()
        self._entries = self._reminders.timeline(now)

        self.table.setRowCount(len(self._entries))
        first_upcoming = None
        for row, entry in enumerate(self._entries):
            sub = entry.subscription
            what = "Free trial ends" if entry.is_trial_end else "Payment"
            if entry.is_trial_end:
                amount = ""
            elif sub.is_shared:
                amount = f"{sub.my_share:.2f} of {sub.price:.2f} {sub.currency.value}"
            else:
                amount = f"{sub.price:.2f} {sub.currency.value}"
            status = entry.status.value + (f" {entry.detail}" if entry.detail else "")
            cells = [entry.date.strftime("%a %d %b %Y"), sub.name, what, amount, status]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if entry.date < today:
                    item.setForeground(QBrush(QColor("gray")))
                if column == 4 and entry.status in _STATUS_COLOURS:
                    item.setForeground(QBrush(QColor(_STATUS_COLOURS[entry.status])))
                if entry.date == today:
                    font = item.font()
                    font.setWeight(QFont.Bold)
                    item.setFont(font)
                self.table.setItem(row, column, item)
            if first_upcoming is None and entry.date >= today:
                first_upcoming = row

        # Keep the selection on the same item, otherwise scroll to today.
        if selected:
            for row, entry in enumerate(self._entries):
                if (entry.subscription.id, entry.date, entry.is_trial_end) == selected:
                    self.table.selectRow(row)
                    break
        elif first_upcoming is not None:
            self.table.scrollToItem(self.table.item(first_upcoming, 0), QAbstractItemView.PositionAtTop)
        self._update_buttons()

    def selected_entry(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._entries):
            return None
        entry = self._entries[rows[0].row()]
        return entry.subscription.id, entry.date, entry.is_trial_end

    def _selected(self) -> TimelineEntry | None:
        rows = self.table.selectionModel().selectedRows()
        return self._entries[rows[0].row()] if rows else None

    def _update_buttons(self) -> None:
        entry = self._selected()
        self.paid_button.setEnabled(bool(entry and entry.can_mark_paid))
        self.unpaid_button.setEnabled(bool(entry and entry.status is TimelineStatus.PAID))

    def mark_selected_paid(self) -> None:
        entry = self._selected()
        if entry and entry.can_mark_paid:
            self._reminders.mark_paid(entry.subscription.id, entry.date, self._now())
            self.changed.emit()

    def unmark_selected_paid(self) -> None:
        entry = self._selected()
        if entry and entry.status is TimelineStatus.PAID:
            self._reminders.unmark_paid(entry.subscription.id, entry.date)
            self.changed.emit()

    def _toggle_paid(self) -> None:
        entry = self._selected()
        if entry is None or entry.is_trial_end:
            return
        if entry.status is TimelineStatus.PAID:
            self.unmark_selected_paid()
        else:
            self.mark_selected_paid()
