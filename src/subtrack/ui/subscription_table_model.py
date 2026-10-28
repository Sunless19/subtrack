"""Qt table model that shows SubscriptionRow objects, plus the proxy that searches, filters and sorts it."""

from decimal import Decimal

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor

from subtrack.domain.models import BillingCycle, Category
from subtrack.services.subscription_service import SubscriptionRow
from subtrack.ui.badge import badge_icon

_HEADERS = ["Name", "Category", "Price", "Cycle", "Per month", "Next payment", "Spent so far"]
_CYCLE_ORDER = {cycle: i for i, cycle in enumerate(BillingCycle)}
_MONEY_COLUMNS = (2, 4, 6)

SORT_ROLE = Qt.UserRole + 1
SEARCH_ROLE = Qt.UserRole + 2


class SubscriptionTableModel(QAbstractTableModel):
    def __init__(self, to_base=None, parent=None):
        """to_base(amount, currency) converts to the base currency, so price columns sort correctly
        across currencies. Without it amounts sort as plain numbers."""
        super().__init__(parent)
        self._rows: list[SubscriptionRow] = []
        self._spent: dict[int, Decimal] = {}
        self._base_code = ""
        self._to_base = to_base or (lambda amount, currency: amount)

    def set_rows(self, rows: list[SubscriptionRow], spent: dict[int, Decimal] | None = None, base_code: str = "") -> None:
        """spent: subscription id -> total spent so far in the base currency (base_code)."""
        self.beginResetModel()
        self._rows = rows
        self._spent = spent or {}
        self._base_code = base_code
        self.endResetModel()

    def row_at(self, row: int) -> SubscriptionRow:
        return self._rows[row]

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return _HEADERS[section]
        if role == Qt.ToolTipRole and section == 6:
            return "Your share of every payment since the first one, using the price at the time."
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        sub = row.subscription
        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:
                tags = []
                if row.in_trial:
                    tags.append("trial")
                if sub.is_shared:
                    tags.append(f"split {sub.shared_with} ways")
                if row.paused:
                    if sub.paused_from == sub.paused_until:
                        tags.append(f"skipping {sub.paused_from:%d %b}")
                    else:
                        tags.append(f"paused until {sub.paused_until:%d %b}")
                if row.cancel_by:
                    tags.append(f"cancel by {row.cancel_by:%d %b %Y}")
                if not sub.active:
                    tags.append("cancelled")
                return sub.name + (f"  ({', '.join(tags)})" if tags else "")
            if column == 1:
                return sub.category.label
            if column == 2:
                if row.promo_active:
                    return f"{sub.promo_price:.2f} {sub.currency.value}  (intro until {sub.promo_until:%d %b})"
                text = f"{sub.price:.2f} {sub.currency.value}"
                change = row.price_change_percent
                if change:
                    text += f"  {'▲' if change > 0 else '▼'}{abs(change)}%"
                return text
            if column == 3:
                return sub.billing_cycle.label
            if column == 4:
                return f"{row.monthly_cost:.2f} {sub.currency.value}"
            if column == 5:
                return row.next_payment.strftime("%d %b %Y") if sub.active else "—"
            if column == 6:
                spent = self._spent.get(sub.id)
                return f"{spent:.2f} {self._base_code}" if spent is not None else "—"

        if role == Qt.DecorationRole and column == 0:
            return badge_icon(sub.name)

        if role == SORT_ROLE:
            return [
                sub.name.lower(),
                sub.category.label,
                float(self._to_base(sub.price, sub.currency)),
                _CYCLE_ORDER[sub.billing_cycle],
                float(self._to_base(row.monthly_cost, sub.currency)),
                row.next_payment.toordinal() if sub.active else 10**9,
                float(self._spent.get(sub.id, -1)),
            ][column]

        if role == SEARCH_ROLE:
            return f"{sub.name} {sub.category.label} {sub.notes} {sub.payment_method}".lower()

        if role == Qt.TextAlignmentRole and column in _MONEY_COLUMNS:
            return int(Qt.AlignRight | Qt.AlignVCenter)

        if role == Qt.ForegroundRole and not sub.active:
            return QBrush(QColor("gray"))

        if role == Qt.ToolTipRole:
            return self._tooltip(row, column)

        return None

    @staticmethod
    def _tooltip(row: SubscriptionRow, column: int) -> str | None:
        sub = row.subscription
        if column == 2 and row.promo_active:
            return f"Introductory price until {sub.promo_until:%d %b %Y}, then {sub.price:.2f} {sub.currency.value}."
        if column == 2 and row.price_history:
            first = row.price_history[0]
            text = f"Was {first.old_price:.2f} {first.old_currency.value} until {first.changed_on:%d %b %Y}"
            if row.price_change_percent is not None:
                text += f" ({row.price_change_percent:+}% since then)"
            return text + f". {len(row.price_history)} price change(s); open Edit to see all."
        if column == 4 and sub.is_shared:
            return f"Your share: full price {sub.price:.2f} {sub.currency.value} split between {sub.shared_with} people."
        if column == 0 and row.cancel_by:
            notice = f" ({sub.notice_days} days' notice)" if sub.notice_days else ""
            return f"Contract ends {sub.contract_end_date:%d %b %Y}{notice}. Cancel by {row.cancel_by:%d %b %Y} to stop it renewing."
        if column == 0 and sub.payment_method:
            return f"Paid with {sub.payment_method}"
        if sub.rarely_used:
            return "Marked as rarely used - consider cancelling it."
        return None


class SubscriptionFilterModel(QSortFilterProxyModel):
    """Search box text, category and payment-method filters, 'show cancelled'; sorts by SORT_ROLE."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self._text = ""
        self._category: Category | None = None
        self._payment_method: str | None = None
        self._show_cancelled = False

    def set_search_text(self, text: str) -> None:
        self._refilter(lambda: setattr(self, "_text", text.strip().lower()))

    def set_category(self, category: Category | None) -> None:
        self._refilter(lambda: setattr(self, "_category", category))

    def set_payment_method(self, method: str | None) -> None:
        """None = any; "" = subscriptions with no payment method set."""
        self._refilter(lambda: setattr(self, "_payment_method", method))

    def set_show_cancelled(self, show: bool) -> None:
        self._refilter(lambda: setattr(self, "_show_cancelled", show))

    def _refilter(self, change) -> None:
        # Qt 6.10+ replaces invalidateFilter() with begin/endFilterChange().
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
            change()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            change()
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model: SubscriptionTableModel = self.sourceModel()
        sub = model.row_at(source_row).subscription
        if not sub.active and not self._show_cancelled:
            return False
        if self._category is not None and sub.category is not self._category:
            return False
        if self._payment_method is not None and sub.payment_method != self._payment_method:
            return False
        if self._text:
            haystack = model.data(model.index(source_row, 0), SEARCH_ROLE)
            return all(word in haystack for word in self._text.split())
        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        return self.sourceModel().data(left, SORT_ROLE) < self.sourceModel().data(right, SORT_ROLE)


def total_of(rows: list[SubscriptionRow], to_base) -> Decimal:
    return sum((to_base(r.monthly_cost, r.subscription.currency) for r in rows), Decimal("0.00"))
