import tarfile
import logging

logger = logging.getLogger(__name__)

try:
    import xz as _xz
    _HAS_XZ = True
except ImportError:
    _HAS_XZ = False


class ArchiveReader:
    def read_member(self, tar_path: str, member_name: str) -> str:
        if _HAS_XZ:
            try:
                with _xz.open(tar_path) as xz_file:
                    with tarfile.open(fileobj=xz_file) as tar:
                        return self._extract(tar, member_name, tar_path)
            except (FileNotFoundError, KeyError):
                raise
            except Exception:
                pass  # fall through to sequential decompress
        with tarfile.open(tar_path, "r:xz") as tar:
            return self._extract(tar, member_name, tar_path)

    def list_members(self, tar_path: str) -> list[str]:
        if _HAS_XZ:
            try:
                with _xz.open(tar_path) as xz_file:
                    with tarfile.open(fileobj=xz_file) as tar:
                        return [m.name for m in tar.getmembers() if m.isfile()]
            except Exception:
                pass
        with tarfile.open(tar_path, "r:xz") as tar:
            return [m.name for m in tar.getmembers() if m.isfile()]

    def _extract(self, tar: tarfile.TarFile, member_name: str, tar_path: str) -> str:
        try:
            f = tar.extractfile(member_name)
        except KeyError:
            raise FileNotFoundError(f"Member {member_name!r} not in {tar_path}")
        if f is None:
            raise FileNotFoundError(f"Member {member_name!r} not in {tar_path}")
        return f.read().decode("utf-8")
