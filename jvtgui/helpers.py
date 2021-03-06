import itertools
import platform
import tempfile
import shutil
import re

from io import BytesIO
from pathlib import Path

import requests
import patoolib


from PyQt5.QtCore import QThread, QProcess, QUrl
from PyQt5.QtWidgets import QFileDialog
from PyQt5 import QtCore
from PyQt5.Qt import QDesktopServices


# Wraps a function and returns None when specified exceptions are thrown.
def wrap_throwable(func, *exc):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except exc:
            return None

    return wrapper


def make_slot(*args, **kwargs):
    def wrapper(func):
        # Convert "snake_case" to "camelCase" for the name of the Qt slot.
        kwargs.setdefault("name", func.__name__.replace("_", " ").title().replace(" ", ""))

        return QtCore.pyqtSlot(*args, **kwargs)(func)

    return wrapper


def pick_directory(parent, title="Select Directory", start=Path("~")):
    path = QFileDialog.getExistingDirectory(
        parent, title, str(start.resolve()), QFileDialog.ShowDirsOnly
    )

    if path:
        return Path(path)

    return start


def pick_file(parent, title="Select File", path=Path("~"), types=("Text Document (*.txt)",)):
    if path.is_file():
        start = path.parent.resolve()
    else:
        start = path.resolve()

    file = QFileDialog.getOpenFileName(parent, title, str(start), filter="\n".join(types))[0]

    if file:
        return Path(file)

    return path


# Decorator for functions to be automatically connected to a signal.
def connect_slot(signal, *args, **kwargs):
    del args, kwargs

    def wrapper(func):
        signal.connect(func)

        return func

    return wrapper


# Generator that yields the cartesian products of a polymorphic dictionary.
def product_dicts(**kwargs):
    keys = kwargs.keys()
    values = kwargs.values()

    for instance in itertools.product(*values):
        yield dict(zip(keys, instance))


# Opens the system's file manager on a file, or open a directory.
# On Windows and Mac, the explorer window will open with the specified file selected,
# much like Chrome's "Show in folder" behavior for downloads.
def open_explorer(path):
    path = Path(path).resolve()
    system = platform.system().lower()

    if system == "windows":
        if path.is_dir():
            # The path is a directory.
            QProcess.startDetached(f'explorer.exe "{path}"')
        else:
            # THe path is a file, open the parent directory and select the file in the view.
            QProcess.startDetached(f'explorer.exe /select,"{path}"')
    elif system == "darwin":
        # Apple's "open" command handles "show in folder" with the "--reveal" flag.
        QProcess.startDetached(f'open -R "{path}"')
    else:
        # The platform is not Windows or Mac, must be Linux?
        # Open the directory with generic handling provided by Qt.

        if path.is_dir():
            QDesktopServices.openUrl(QUrl(path.as_uri()))
        else:
            # If the path provided is a file, Qt needs to open the parent directory.
            QDesktopServices.openUrl(QUrl(path.parent.as_uri()))


class BackgroundThread(QThread):
    def __init__(self, destination, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._target = None
        self._args = None
        self._kwargs = None

        destination.append(self)

    def __call__(self, function):
        self._target = function

        def wrapper(*args, **kwargs):
            self._args = args
            self._kwargs = kwargs

            self.start()

        return wrapper

    def __del__(self):
        self.wait()

    def run(self):
        self._target(*self._args, **self._kwargs)


class ExtractionThread(QThread):
    begin_extract = QtCore.pyqtSignal(str)
    endExtract = QtCore.pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.source_file = None
        self.dest_dir = None
        self.success = True
        self._stopped = False

    def __del__(self):
        self.wait()

    def __call__(self, source, destination):
        self.source_file = source
        self.dest_dir = destination

        self.start()

    def stop(self):
        self._stopped = True
        self.success = False
        self.endExtract.emit(str(self.dest_dir))
        self.exit(0)

    def run(self):
        self._stopped = False
        self.success = False
        self.begin_extract.emit(str(self.dest_dir))

        source_path = str(self.source_file.resolve())
        dest_path = str(self.dest_dir.resolve())
        temp_dest_path = tempfile.mkdtemp()
        temp_dir = Path(temp_dest_path)

        patoolib.extract_archive(source_path, outdir=temp_dest_path)

        for member in map(lambda x: x.name, temp_dir.glob("*")):
            if member in map(lambda x: x.name, self.dest_dir.glob("*")):
                print("MEMBER:", member)
                shutil.rmtree(self.dest_dir / member)

                print("Deleting directory", member)

            shutil.move(temp_dir / member, self.dest_dir / member)

        self.success = True
        self.endExtract.emit(str(self.dest_dir))


class DownloaderThread(QThread):
    filenameFound = QtCore.pyqtSignal(str)
    filesizeFound = QtCore.pyqtSignal(int)
    bytesChanged = QtCore.pyqtSignal(int)
    chunkWritten = QtCore.pyqtSignal(int)
    beginSendRequest = QtCore.pyqtSignal()
    endSendRequest = QtCore.pyqtSignal()
    beginDownload = QtCore.pyqtSignal(str)
    endDownload = QtCore.pyqtSignal(str)

    def __init__(self, *args, chunk_size=1024, use_bytesio=False, **kwargs):
        super().__init__(*args, **kwargs)

        self.chunk_size = chunk_size
        self.use_bytesio = use_bytesio
        self.filename = None
        self.filesize = None
        self.downloaded_bytes = 0
        self._url = None
        self._location = None
        self.file_location = None
        self.part_location = None
        self.success = False
        self._stopped = False

    def __del__(self):
        self.wait()

    def __call__(self, url, location="./"):
        self._url = url
        self._location = location

        self.start()

    def stop(self):
        self._stopped = True
        self.success = False
        self.endDownload.emit(str(self.file_location))
        self.exit(0)

    def run(self):
        self._stopped = False
        self.success = False

        self.beginSendRequest.emit()

        with requests.get(self._url, stream=True) as request:
            self.endSendRequest.emit()

            request.raise_for_status()

            self.filesize = int(request.headers["content-length"])
            self.filename = re.findall(r"filename=(.+)", request.headers["content-disposition"])[0]

            self.filenameFound.emit(self.filename)
            self.filesizeFound.emit(self.filesize)

            self.file_location = Path(self._location, self.filename).resolve()
            self.part_location = Path(self.file_location).resolve()
            self.part_location = (self.file_location.parent / self.file_location.name).with_suffix(
                self.file_location.suffix + ".part"
            )

            print(self.file_location)
            print(self.part_location)

            self.downloaded_bytes = 0

            self.beginDownload.emit(str(self.file_location))

            if self.use_bytesio:
                part_file = BytesIO()
            else:
                part_file = open(self.part_location, "wb")

            for count, chunk in enumerate(request.iter_content(chunk_size=self.chunk_size)):
                if self._stopped:
                    return

                if not chunk:
                    continue

                part_file.write(chunk)
                self.downloaded_bytes += len(chunk)

                self.bytesChanged.emit(self.downloaded_bytes)
                self.chunkWritten.emit(count)

            part_file.flush()

        if self.use_bytesio:
            with open(self.file_location, "wb") as final_file:
                part_file.seek(0)

                final_file.write(part_file.read())

            part_file.close()
        else:
            part_file.close()

            self.part_location.replace(self.file_location)

        self.success = True
        self.endDownload.emit(str(self.file_location))
