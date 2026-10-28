"""Main window: subscription list with add / edit / delete, plus Dashboard and Reminders tabs."""

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QTableView,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from subtrack import paths
from subtrack.data.settings_repository import SettingsRepository
from subtrack.services.autostart_service import AutostartService
from subtrack.services.currency_service import CurrencyService
from subtrack.services.export_service import ExportService, ImportFailed
from subtrack.services.reminder_service import ReminderService
from subtrack.services.stats_service import StatsService
from subtrack.services.subscription_service import SubscriptionService, ValidationError
from subtrack.ui.dashboard_view import DashboardView
from subtrack.ui.reminders_view import RemindersView
from subtrack.ui.settings_dialog import SettingsDialog
from subtrack.ui.subscription_dialog import SubscriptionDialog
from subtrack.domain.models import Category
from subtrack.ui.subscription_table_model import SubscriptionFilterModel, SubscriptionTableModel, total_of


class MainWindow(QMainWindow):
    hidden_to_tray = Signal()

    def __init__(
        self,
        subscriptions: SubscriptionService,
        stats: StatsService,
        currency: CurrencyService,
        settings: SettingsRepository,
        exporter: ExportService,
        autostart: AutostartService,
        reminders: ReminderService,
    ):
        super().__init__()
        self._subscriptions = subscriptions
        self._stats = stats
        self._currency = currency
        self._settings = settings
        self._exporter = exporter
        self._autostart = autostart
        # Set by app.py when a system tray is available: closing then hides instead of quitting.
        self.hide_on_close = False
        self.setWindowTitle("SubTrack")
        self.resize(960, 560)

        self.model = SubscriptionTableModel(currency.to_base, self)
        self.proxy = SubscriptionFilterModel(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.doubleClicked.connect(self.edit_selected)
        self.table.selectionModel().selectionChanged.connect(self._update_actions)

        # Search / filter bar above the list.
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name, category or notes…  (Ctrl+F)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filters)
        self.category_filter = QComboBox()
        self.category_filter.addItem("All categories", None)
        for category in Category:
            self.category_filter.addItem(category.label, category)
        self.category_filter.currentIndexChanged.connect(self._apply_filters)
        self.show_cancelled_check = QCheckBox("Show cancelled")
        self.show_cancelled_check.toggled.connect(self._apply_filters)
        self.filter_summary = QLabel()
        self.filter_summary.setStyleSheet("color: gray;")
        QShortcut(QKeySequence.Find, self, activated=self._focus_search)

        filter_bar = QHBoxLayout()
        filter_bar.addWidget(self.search_edit, 2)
        filter_bar.addWidget(self.category_filter)
        filter_bar.addWidget(self.show_cancelled_check)
        filter_bar.addWidget(self.filter_summary, 1, Qt.AlignRight)
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 6, 0, 0)
        list_layout.addLayout(filter_bar)
        list_layout.addWidget(self.table)

        self.dashboard = DashboardView(stats, currency)
        self.reminders_view = RemindersView(reminders)
        self.reminders_view.changed.connect(self.refresh)
        self.tabs = QTabWidget()
        self.tabs.addTab(list_page, "Subscriptions")
        self.tabs.addTab(self.dashboard, "Dashboard")
        self.tabs.addTab(self.reminders_view, "Reminders")
        self.setCentralWidget(self.tabs)

        self.add_action = QAction("Add", self, shortcut=QKeySequence.New, triggered=self.add)
        self.edit_action = QAction("Edit", self, triggered=self.edit_selected)
        self.cancel_action = QAction("Mark cancelled", self, triggered=self.cancel_selected)
        self.delete_action = QAction("Delete", self, shortcut=QKeySequence.Delete, triggered=self.delete_selected)
        self.export_action = QAction("Export…", self, triggered=self.export_data)
        self.import_action = QAction("Import…", self, triggered=self.import_data)
        self.settings_action = QAction("Settings", self, triggered=self.open_settings)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.addActions([self.add_action, self.edit_action, self.cancel_action, self.delete_action])
        toolbar.addSeparator()
        toolbar.addActions([self.export_action, self.import_action])
        toolbar.addSeparator()
        toolbar.addAction(self.settings_action)
        self.addToolBar(toolbar)

        self.total_label = QLabel()
        self.statusBar().addPermanentWidget(self.total_label)

        self.refresh()

    def refresh(self) -> None:
        self.model.set_rows(self._subscriptions.list_rows(include_inactive=True))
        base = self._currency.base_currency().value
        self.total_label.setText(
            f"Monthly: {self._stats.monthly_total():.2f} {base}   ·   "
            f"Yearly: {self._stats.yearly_total():.2f} {base}"
        )
        self.dashboard.refresh()
        self.reminders_view.refresh()
        self._update_filter_summary()
        self._update_actions()

    def _focus_search(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _apply_filters(self) -> None:
        self.proxy.set_search_text(self.search_edit.text())
        self.proxy.set_category(self.category_filter.currentData())
        self.proxy.set_show_cancelled(self.show_cancelled_check.isChecked())
        self._update_filter_summary()
        self._update_actions()

    def _update_filter_summary(self) -> None:
        """'Showing 3 of 12 · 85.00 RON/month' while a filter hides something."""
        visible = [self.model.row_at(self.proxy.mapToSource(self.proxy.index(r, 0)).row())
                   for r in range(self.proxy.rowCount())]
        active_total = sum(1 for r in range(self.model.rowCount()) if self.model.row_at(r).subscription.active)
        shown_active = [r for r in visible if r.subscription.active]
        filtering = bool(self.search_edit.text().strip()) or self.category_filter.currentData() is not None
        if not filtering:
            self.filter_summary.setText("")
            return
        base = self._currency.base_currency()
        total = total_of(shown_active, self._currency.to_base)
        self.filter_summary.setText(
            f"Showing {len(shown_active)} of {active_total} · {total:.2f} {base.value}/month"
        )

    def show_reminders_tab(self) -> None:
        self.tabs.setCurrentWidget(self.reminders_view)

    def closeEvent(self, event) -> None:
        if self.hide_on_close:
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
        else:
            super().closeEvent(event)

    def _selected_row(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        return self.model.row_at(self.proxy.mapToSource(indexes[0]).row())

    def _update_actions(self) -> None:
        row = self._selected_row()
        for action in (self.edit_action, self.cancel_action, self.delete_action):
            action.setEnabled(row is not None)
        self.cancel_action.setText("Reactivate" if row and not row.subscription.active else "Mark cancelled")

    def add(self) -> None:
        self._run_dialog(SubscriptionDialog(self), self._subscriptions.add)

    def edit_selected(self) -> None:
        row = self._selected_row()
        if row:
            dialog = SubscriptionDialog(self, row.subscription, row.price_history)
            self._run_dialog(dialog, self._subscriptions.update)

    def cancel_selected(self) -> None:
        row = self._selected_row()
        if not row:
            return
        if not row.subscription.active:
            self._subscriptions.reactivate(row.subscription.id)
            self.refresh()
            return
        answer = QMessageBox.question(
            self,
            "Mark as cancelled",
            f"Mark '{row.subscription.name}' as cancelled? It will no longer count towards totals or reminders.",
        )
        if answer == QMessageBox.Yes:
            self._subscriptions.cancel(row.subscription.id)
            self.refresh()

    def delete_selected(self) -> None:
        row = self._selected_row()
        if not row:
            return
        answer = QMessageBox.question(
            self, "Delete subscription", f"Delete '{row.subscription.name}'? This cannot be undone."
        )
        if answer == QMessageBox.Yes:
            self._subscriptions.delete(row.subscription.id)
            self.refresh()

    def open_settings(self) -> None:
        if SettingsDialog(self._currency, self._settings, self._autostart, self).exec():
            self.refresh()

    # file-dialog filter -> (extension, export method name, what the count means)
    _EXPORT_FORMATS = {
        "CSV for Excel (*.csv)": (".csv", "export_csv", "subscriptions"),
        "JSON backup (*.json)": (".json", "export_json", "subscriptions"),
        "Calendar – next 12 months of payments (*.ics)": (".ics", "export_ics", "payments"),
    }

    def export_data(self) -> None:
        default = Path.home() / "Documents" / f"subtrack-{date.today().isoformat()}.csv"
        if not default.parent.exists():
            default = paths.data_dir() / default.name
        filename, chosen = QFileDialog.getSaveFileName(
            self, "Export subscriptions", str(default), ";;".join(self._EXPORT_FORMATS)
        )
        if not filename:
            return
        path = Path(filename)
        # A typed extension wins over the selected filter.
        by_extension = {ext: name for name, (ext, _, _) in self._EXPORT_FORMATS.items()}
        chosen = by_extension.get(path.suffix.lower(), chosen)
        extension, method, counted = self._EXPORT_FORMATS.get(chosen, next(iter(self._EXPORT_FORMATS.values())))
        path = path.with_suffix(extension)
        try:
            count = getattr(self._exporter, method)(path)
        except OSError as error:
            QMessageBox.warning(self, "Export failed", f"Could not write {path.name}: {error}")
            return
        self.statusBar().showMessage(f"Exported {count} {counted} to {path}", 8000)

    def import_data(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import subscriptions", str(Path.home()), "SubTrack files (*.csv *.json)"
        )
        if not filename:
            return
        try:
            result = self._exporter.import_file(Path(filename))
        except ImportFailed as error:
            QMessageBox.warning(self, "Import failed", f"Nothing was imported.\n\n{error}")
            return
        self.refresh()
        message = f"Imported {result.imported} subscriptions."
        if result.skipped_duplicates:
            message += f"\nSkipped {result.skipped_duplicates} that you already have."
        QMessageBox.information(self, "Import finished", message)

    def _run_dialog(self, dialog: SubscriptionDialog, save) -> None:
        # Keep the dialog open until the data is valid or the user cancels.
        while dialog.exec():
            try:
                save(dialog.subscription())
            except ValidationError as error:
                QMessageBox.warning(self, "Invalid subscription", str(error))
                continue
            self.refresh()
            return
