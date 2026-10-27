"""Qt table model that shows SubscriptionRow objects."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from subtrack.services.subscription_service import SubscriptionRow

_HEADERS = ["Name", "Category", "Price", "Cycle", "Per month", "Next payment"]


class SubscriptionTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[SubscriptionRow] = []

    def set_rows(self, rows: list[SubscriptionRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, row: int) -> SubscriptionRow:
        return self._rows[row]

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        sub = row.subscription
        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:
                return sub.name + ("  (trial)" if row.in_trial else "")
            if column == 1:
                return sub.category.label
            if column == 2:
                return f"{sub.price:.2f} {sub.currency.value}"
            if column == 3:
                return sub.billing_cycle.label
            if column == 4:
                return f"{row.monthly_cost:.2f} {sub.currency.value}"
            if column == 5:
                return row.next_payment.strftime("%d %b %Y")

        if role == Qt.TextAlignmentRole and column in (2, 4):
            return int(Qt.AlignRight | Qt.AlignVCenter)

        if role == Qt.ToolTipRole and sub.rarely_used:
            return "Marked as rarely used - consider cancelling it."

        return None
