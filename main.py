import sys
import platform

from PyQt5.QtWidgets import QApplication, QMainWindow, QHeaderView
from adoptapi import RequestOptions, Release, ReleaseAsset
from interface import Ui_MainWindow
from widgets import CheckBoxButtonGroup
from models import AvailableBinariesTableModel
from utils import DownloaderThread
from filedict import FileDict
from pathlib import Path, PurePath, PosixPath, WindowsPath


PLATFORM_OS = (lambda x: {"darwin": "mac"}.get(x, x))(platform.system().lower())
PLATFORM_ARCH = (
    lambda x: {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64_be": "aarch64",
        "armv8b": "aarch64",
        "armv8l": "aarch64",
        "i386": "x32",
        "i686": "x32",
        "s390": "s390x",
    }.get(x, x)
)(platform.machine().lower())

BINARIES_DIR = Path(Path.home(), ".jvman")
BINARIES_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = Path(BINARIES_DIR, "settings.json")
SETTINGS = FileDict(SETTINGS_FILE)

_serializer = SETTINGS.serializer()

_serializer.add_serializer(Path, lambda x: str(x.resolve()))
_serializer.add_serializer(PurePath, lambda x: str(Path(x.resolve())))
_serializer.add_serializer(PosixPath, lambda x: str(Path(x.resolve())))
_serializer.add_serializer(WindowsPath, lambda x: str(Path(x.resolve())))

_serializer.add_serializer(RequestOptions, RequestOptions.serialize)
_serializer.add_deserializer(RequestOptions.__name__, lambda x: RequestOptions(**x))

_serializer.add_serializer(Release, Release.serialize)
_serializer.add_deserializer(Release.__name__, lambda x: Release(**x))

_serializer.add_serializer(ReleaseAsset, ReleaseAsset.serialize)
_serializer.add_deserializer(ReleaseAsset.__name__, lambda x: ReleaseAsset(**x))


def set_settings_defaults():
    SETTINGS.setdefault("filter_options", RequestOptions(many=True))
    SETTINGS.setdefault("installed_binaries", [])
    SETTINGS.setdefault("download_path", Path(Path.home(), "Downloads"))
    SETTINGS.setdefault("binaries_dir", Path(Path.home(), ".jvman"))

    SETTINGS.dump()


class AppMainWindow(Ui_MainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        SETTINGS.load()
        set_settings_defaults()

        self._download_thread = DownloaderThread(chunk_size=1024)

    def setupUi(self, window, *args, **kwargs):
        super().setupUi(window, *args, **kwargs)

        self.availableBinariesTableModel = AvailableBinariesTableModel()
        self.availableBinariesTableView.setModel(self.availableBinariesTableModel)
        self.availableBinariesTableView.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )

        self.javaVerButtonGroup = CheckBoxButtonGroup(window)
        self.javaVerButtonGroup.setObjectName("javaVerButtonGroup")
        self.javaVerButtonGroup.addButton(self.javaVer8CheckBox)
        self.javaVerButtonGroup.addButton(self.javaVer9CheckBox)
        self.javaVerButtonGroup.addButton(self.javaVer10CheckBox)
        self.javaVerButtonGroup.addButton(self.javaVer11CheckBox)

        self.releaseTypeButtonGroup = CheckBoxButtonGroup(window)
        self.releaseTypeButtonGroup.setObjectName("releaseTypeButtonGroup")
        self.releaseTypeButtonGroup.addButton(self.stableReleaseTypeCheckBox)
        self.releaseTypeButtonGroup.addButton(self.nightlyReleaseTypeCheckBox)

        self.binTypeButtonGroup = CheckBoxButtonGroup(window)
        self.binTypeButtonGroup.setObjectName("binTypeButtonGroup")
        self.binTypeButtonGroup.addButton(self.jdkBinCheckBox)
        self.binTypeButtonGroup.addButton(self.jreBinCheckBox)

        self.vmButtonGroup = CheckBoxButtonGroup(window)
        self.vmButtonGroup.setObjectName("vmButtonGroup")
        self.vmButtonGroup.addButton(self.hotspotVmCheckBox)
        self.vmButtonGroup.addButton(self.openj9VmCheckBox)

        self.heapSizeButtonGroup = CheckBoxButtonGroup(window)
        self.heapSizeButtonGroup.setObjectName("heapSizeButtonGroup")
        self.heapSizeButtonGroup.addButton(self.normalHeapSizeCheckBox)
        self.heapSizeButtonGroup.addButton(self.largeHeapSizeCheckBox)

        self.archButtonGroup = CheckBoxButtonGroup(window)
        self.archButtonGroup.setObjectName("archButtonGroup")
        self.archButtonGroup.addButton(self.x64ArchCheckBox)
        self.archButtonGroup.addButton(self.x32ArchCheckBox)

        if PLATFORM_ARCH == "x32":
            self.archOptionLabel.setEnabled(True)

            self.x32ArchCheckBox.setChecked(True)
            self.x32ArchCheckBox.setEnabled(False)
        elif PLATFORM_ARCH == "x64":
            self.archOptionLabel.setEnabled(True)

            self.x64ArchCheckBox.setChecked(True)
            self.x64ArchCheckBox.setEnabled(False)
            self.x32ArchCheckBox.setEnabled(True)

        self.setup_connections()

    def setup_connections(self):
        def _on_rows_inserted(parent, first, last):
            for row in range(first, last + 1):
                self.availableBinariesTableView.resizeRowToContents(row)

        self.availableBinariesTableModel.rowsInserted.connect(_on_rows_inserted)
        self.availableBinariesTableModel.status_change.connect(self.statusbar.showMessage)

        for group in [
            self.javaVerButtonGroup,
            self.releaseTypeButtonGroup,
            self.binTypeButtonGroup,
            self.vmButtonGroup,
            self.heapSizeButtonGroup,
            self.archButtonGroup,
        ]:
            group.buttonToggled.connect(
                lambda: self.availableBinariesTableModel.populate_model(self.filter_options())
            )

        def _on_begin_send_request():
            self.availableBinariesProgressBar.setMaximum(0)

        self._download_thread.beginSendRequest.connect(_on_begin_send_request)

        def _on_begin_download():
            self.availableBinariesProgressBar.setMaximum(self._download_thread.filesize)
            self.availableBinariesProgressBar.setFormat("Downloading... %p%")

        self._download_thread.beginDownload.connect(_on_begin_download)

        def _on_end_download():
            self.availableBinariesProgressBar.setFormat(
                f'Downloaded "{self._download_thread.filename}" successfully!'
            )

            self.availableBinariesTableView.setEnabled(True)
            self.availableBinariesDownloadButton.setEnabled(True)
            self.availableBinariesInstallButton.setEnabled(True)
            self.filterOptionsGroupBox.setEnabled(True)

            self.availableBinariesTableView.setFocus()

        self._download_thread.endDownload.connect(_on_end_download)

        self._download_thread.filesizeFound.connect(self.availableBinariesProgressBar.setMaximum)
        self._download_thread.bytesChanged.connect(self.availableBinariesProgressBar.setValue)

        self.availableBinariesInfoButton.clicked.connect(self.open_info_window)
        self.availableBinariesDownloadButton.clicked.connect(self.download_selected_binary)
        self.availableBinariesInstallButton.clicked.connect(self.install_selected_binary)

        def _on_selection_changed(selected, deselected):
            self.enable_available_binaries_tab_actions(True)
            self.availableBinariesProgressBar.setMaximum(1)
            self.availableBinariesProgressBar.setValue(0)

        self.availableBinariesTableView.selectionModel().selectionChanged.connect(
            _on_selection_changed
        )

    def open_info_window(self, _):
        print("open_info_window")

    def download_selected_binary(self, _):
        print("download_selected_binary")

        self.availableBinariesTableView.setEnabled(False)
        self.availableBinariesDownloadButton.setEnabled(False)
        self.availableBinariesInstallButton.setEnabled(False)
        self.filterOptionsGroupBox.setEnabled(False)

        request_url = self.selected_release().binaries[0].binary_link

        self._download_thread(request_url, location=SETTINGS["download_path"])

    def install_selected_binary(self, _):
        print("install_selected_binary")

        SETTINGS["installed_binaries"].append(self.selected_release())

        SETTINGS.dump()

    def selected_release(self):
        return self.availableBinariesTableModel.data(
            self.availableBinariesTableView.selectedIndexes()[0],
            AvailableBinariesTableModel.ObjectRole,
        )

    def enable_available_binaries_tab_actions(self, enable=True):
        self.availableBinariesInfoButton.setEnabled(True)
        self.availableBinariesDownloadButton.setEnabled(True)
        self.availableBinariesInstallButton.setEnabled(True)
        self.availableBinariesProgressBar.setEnabled(True)

    def filter_options(self):
        options = RequestOptions(many=True, os=[PLATFORM_OS])

        if self.javaVer8CheckBox.isChecked():
            options._version.append("openjdk8")

        if self.javaVer9CheckBox.isChecked():
            options._version.append("openjdk9")

        if self.javaVer10CheckBox.isChecked():
            options._version.append("openjdk10")

        if self.javaVer11CheckBox.isChecked():
            options._version.append("openjdk11")

        if self.stableReleaseTypeCheckBox.isChecked():
            options._nightly.append(False)

        if self.nightlyReleaseTypeCheckBox.isChecked():
            options._nightly.append(True)

        if self.hotspotVmCheckBox.isChecked():
            options.openjdk_impl.append("hotspot")

        if self.openj9VmCheckBox.isChecked():
            options.openjdk_impl.append("openj9")

        if PLATFORM_ARCH == "x64":
            if self.x32ArchCheckBox.isChecked():
                options.arch.append("x32")

            if self.x64ArchCheckBox.isChecked():
                options.arch.append("x64")
        else:
            options.arch.append(PLATFORM_ARCH)

        if self.jdkBinCheckBox.isChecked():
            options.type.append("jdk")

        if self.jreBinCheckBox.isChecked():
            options.type.append("jre")

        if self.normalHeapSizeCheckBox.isChecked():
            options.heap_size.append("normal")

        if self.largeHeapSizeCheckBox.isChecked():
            options.heap_size.append("large")

        return options


if __name__ == "__main__":
    app = QApplication([])
    window = QMainWindow()
    ui = AppMainWindow()
    ui.setupUi(window)
    window.show()
    ui.availableBinariesTableModel.populate_model(ui.filter_options())
    sys.exit(app.exec_())
