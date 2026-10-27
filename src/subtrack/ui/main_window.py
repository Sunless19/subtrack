"""Main window: subscription list with add / edit / delete, and a dashboard tab."""

from datetime import date
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTableView,
    QTabWidget,
    QToolBar,
)

from subtrack import paths
from subtrack.data.settings_repository import SettingsRepository
from subtrack.services.autostart_service import AutostartService
from subtrack.services.currency_service import CurrencyService
from subtrack.services.export_service import ExportService, ImportFailed
from subtrack.services.stats_service import StatsService
from subtrack.services.subscription_service import SubscriptionService, ValidationError
from subtrack.ui.dashboard_view import DashboardView
from subtrack.ui.settings_dialog import SettingsDialog
from subtrack.ui.subscription_dialog import SubscriptionDialog
from subtrack.ui.subscription_table_model import SubscriptionTableModel


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

        self.model = SubscriptionTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.doubleClicked.connect(self.edit_selected)
        self.table.selectionModel().selectionChanged.connect(self._update_actions)

        self.dashboard = DashboardView(stats, currency)
        tabs = QTabWidget()
        tabs.addTab(self.table, "Subscriptions")
        tabs.addTab(self.dashboard, "Dashboard")
        self.setCentralWidget(tabs)

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
        self.model.set_rows(self._subscriptions.list_rows())
        base = self._currency.base_currency().value
        self.total_label.setText(
            f"Monthly: {self._stats.monthly_total():.2f} {base}   ·   "
            f"Yearly: {self._stats.yearly_total():.2f} {base}"
        )
        self.dashboard.refresh()
        self._update_actions()

    def closeEvent(self, event) -> None:
        if self.hide_on_close:
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
        else:
            super().closeEvent(event)

    def _selected_row(self):
        indexes = self.table.selectionModel().selectedRows()
        return self.model.row_at(indexes[0].row()) if indexes else None

    def _update_actions(self) -> None:
        has_selection = self._selected_row() is not None
        for action in (self.edit_action, self.cancel_action, self.delete_action):
            action.setEnabled(has_selection)

    def add(self) -> None:
        self._run_dialog(SubscriptionDialog(self), self._subscriptions.add)

    def edit_selected(self) -> None:
        row = self._selected_row()
        if row:
            self._run_dialog(SubscriptionDialog(self, row.subscription), self._subscriptions.update)

    def cancel_selected(self) -> None:
        row = self._selected_row()
        if not row:
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

    _CSV_FILTER = "CSV for Excel (*.csv)"
    _JSON_FILTER = "JSON backup (*.json)"

    def export_data(self) -> None:
        default = Path.home() / "Documents" / f"subtrack-{date.today().isoformat()}.csv"
        if not default.parent.exists():
            default = paths.data_dir() / default.name
        filename, chosen = QFileDialog.getSaveFileName(
            self, "Export subscriptions", str(default), f"{self._CSV_FILTER};;{self._JSON_FILTER}"
        )
        if not filename:
            return
        path = Path(filename)
        as_json = chosen == self._JSON_FILTER or path.suffix.lower() == ".json"
        path = path.with_suffix(".json" if as_json else ".csv")
        try:
            count = (self._exporter.export_json if as_json else self._exporter.export_csv)(path)
        except OSError as error:
            QMessageBox.warning(self, "Export failed", f"Could not write {path.name}: {error}")
            return
        self.statusBar().showMessage(f"Exported {count} subscriptions to {path}", 8000)

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
