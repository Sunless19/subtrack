"""Settings: base currency, exchange rates, reminder timing and autostart."""

from decimal import Decimal

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QMessageBox,
    QSpinBox,
)

from subtrack.data.settings_repository import SettingsRepository
from subtrack.domain.models import Currency
from subtrack.services.autostart_service import AutostartService
from subtrack.services.currency_service import CurrencyService


class SettingsDialog(QDialog):
    def __init__(
        self,
        currency: CurrencyService,
        settings: SettingsRepository,
        autostart: AutostartService,
        parent=None,
    ):
        super().__init__(parent)
        self._currency = currency
        self._settings = settings
        self._autostart = autostart
        self.setWindowTitle("Settings")

        self.base_combo = QComboBox()
        for cur in Currency:
            self.base_combo.addItem(cur.value, cur)
        self.base_combo.setCurrentIndex(self.base_combo.findData(currency.base_currency()))

        self.rate_spins: dict[Currency, QDoubleSpinBox] = {}
        for cur in Currency:
            if cur is Currency.RON:
                continue
            spin = QDoubleSpinBox()
            spin.setRange(0.0001, 10_000)
            spin.setDecimals(4)
            spin.setSuffix(" RON")
            spin.setValue(float(currency.rate_in_ron(cur)))
            self.rate_spins[cur] = spin

        self.days_spin = QSpinBox()
        self.days_spin.setRange(0, 30)
        self.days_spin.setSuffix(" days before")
        self.days_spin.setValue(int(settings.get("reminder_days_before", "3")))

        self.autostart_check = QCheckBox("Start SubTrack when I sign in to Windows")
        self.autostart_check.setEnabled(autostart.is_supported())
        self.autostart_check.setChecked(autostart.is_enabled())
        if autostart.is_enabled() and not autostart.is_current():
            self.autostart_check.setToolTip("The startup entry points to another copy. Saving will update it.")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow("Show totals in", self.base_combo)
        for cur, spin in self.rate_spins.items():
            form.addRow(f"1 {cur.value} =", spin)
        form.addRow("Remind me", self.days_spin)
        form.addRow("", self.autostart_check)
        form.addRow(buttons)

    def accept(self) -> None:
        # Qt hands str-based enums back as plain str, so convert them again.
        self._currency.set_base_currency(Currency(self.base_combo.currentData()))
        for cur, spin in self.rate_spins.items():
            self._currency.set_rate_in_ron(cur, Decimal(f"{spin.value():.4f}"))
        self._settings.set("reminder_days_before", str(self.days_spin.value()))

        if self._autostart.is_supported():
            wanted = self.autostart_check.isChecked()
            # Rewrite when enabled so a stale entry (app moved) gets fixed too.
            if wanted or self._autostart.is_enabled():
                try:
                    self._autostart.set_enabled(wanted)
                except OSError as error:
                    QMessageBox.warning(self, "Start with Windows", f"Could not change the startup setting: {error}")
        super().accept()
