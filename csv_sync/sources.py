"""File sources: where the CSV exports are pulled from.

* LocalFolderSource - a local folder or a UNC path (\\\\server\\share\\dir). Use this
  when the service runs on Windows under an account that has read access to the share.
* SMBSource - connects to the Windows file server over SMB3 from any OS
  (requires the optional `smbprotocol` package). Encryption is required by default.
"""

import fnmatch
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from csv_sync.config import SyncConfig


@dataclass(frozen=True)
class RemoteFile:
    name: str      # path relative to the source root, used as the stable file key
    size: int
    mtime: float


class FileSource(ABC):
    @abstractmethod
    def list_files(self) -> List[RemoteFile]:
        pass

    @abstractmethod
    def read_bytes(self, name: str, max_bytes: int) -> bytes:
        pass


def _read_limited(fh, max_bytes: int, name: str) -> bytes:
    data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"{name} exceeds the {max_bytes}-byte limit")
    return data


def _safe_join(root: str, name: str) -> str:
    path = os.path.normpath(os.path.join(root, name))
    root_norm = os.path.normpath(root)
    if os.path.commonpath([path, root_norm]) != root_norm:
        raise ValueError(f"Refusing to read outside the source folder: {name}")
    return path


class LocalFolderSource(FileSource):
    def __init__(self, root: str, pattern: str):
        self.root = root
        self.pattern = pattern

    def list_files(self) -> List[RemoteFile]:
        files = []
        with os.scandir(self.root) as entries:
            for entry in entries:
                if entry.is_file() and fnmatch.fnmatch(entry.name.lower(), self.pattern.lower()):
                    st = entry.stat()
                    files.append(RemoteFile(entry.name, st.st_size, st.st_mtime))
        return sorted(files, key=lambda f: (f.mtime, f.name))

    def read_bytes(self, name: str, max_bytes: int) -> bytes:
        with open(_safe_join(self.root, name), "rb") as fh:
            return _read_limited(fh, max_bytes, name)


class SMBSource(FileSource):
    def __init__(self, server: str, share: str, folder: str, pattern: str,
                 username: str, password: str, require_encryption: bool = True):
        try:
            import smbclient  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("SMB source requires: pip install smbprotocol") from exc
        self._smb = smbclient
        self._smb.register_session(server, username=username, password=password,
                                   encrypt=require_encryption)
        self.root = rf"\\{server}\{share}" + (rf"\{folder.strip(chr(92))}" if folder else "")
        self.pattern = pattern

    def list_files(self) -> List[RemoteFile]:
        files = []
        for entry in self._smb.scandir(self.root):
            if entry.is_file() and fnmatch.fnmatch(entry.name.lower(), self.pattern.lower()):
                st = entry.stat()
                files.append(RemoteFile(entry.name, st.st_size, st.st_mtime))
        return sorted(files, key=lambda f: (f.mtime, f.name))

    def read_bytes(self, name: str, max_bytes: int) -> bytes:
        if "\\" in name or "/" in name or name in ("..", "."):
            raise ValueError(f"Refusing to read outside the source folder: {name}")
        with self._smb.open_file(self.root + "\\" + name, mode="rb") as fh:
            return _read_limited(fh, max_bytes, name)


def build_source(cfg: SyncConfig) -> FileSource:
    if cfg.source_type == "smb":
        return SMBSource(cfg.smb_server, cfg.smb_share, cfg.source_path, cfg.file_pattern,
                         cfg.smb_username, cfg.smb_password, cfg.smb_require_encryption)
    return LocalFolderSource(cfg.source_path, cfg.file_pattern)
