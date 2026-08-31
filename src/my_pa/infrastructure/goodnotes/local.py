"""Read-only local GoodNotes page source and bounded local OCR boundary.

The source is admitted by an explicit manifest under one explicit root.  It
does not crawl a directory or parse ``.goodnotes`` archives.  Every page names
its canonical source identities, immutable version, media type, observed time,
relative representation path, and expected digest.  Reads refuse links,
escapes, non-regular files, digest drift, oversized files, duplicate identities,
and over-wide manifests.

The OCR adapter executes one explicitly supplied local command without a shell.
It streams one admitted page representation on stdin and accepts a small JSON
region envelope on stdout.  The executable, timeout, input/output sizes, region
count, coordinates, transcription size, and confidence are all bounded.  This
module does not select or download an OCR engine and has no cloud/model client.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Final

from my_pa.application.goodnotes import GoodNotesSourceLiveness, GoodNotesSourceLivenessReceipt
from my_pa.domain.goodnotes.models import RegionBox, SourcePage, TranscribedRegion

_MANIFEST_SCHEMA: Final = "my-pa.goodnotes-local-source.v1"
_MAX_MANIFEST_BYTES: Final = 1_048_576
_MAX_PAGES: Final = 500
_MAX_PAGE_BYTES: Final = 25 * 1_048_576
_MAX_OCR_OUTPUT_BYTES: Final = 2 * 1_048_576
_MAX_REGIONS: Final = 250
_SUPPORTED_MEDIA_TYPES: Final = frozenset({"application/pdf", "image/jpeg", "image/png"})
_SUFFIX_MEDIA_TYPES: Final = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)


class GoodNotesLocalSourceError(ValueError):
    """A local manifest or page failed the read-only admission contract."""


class GoodNotesSourceMissingError(GoodNotesLocalSourceError):
    """An explicitly named source path was absent at observation time."""


class GoodNotesTranscriptionError(RuntimeError):
    """The bounded local OCR boundary failed without exposing its output."""


@dataclass(frozen=True, slots=True)
class ManifestGoodNotesSource:
    """One explicitly admitted, manifest-indexed local source root."""

    root: Path
    manifest_relative_path: PurePosixPath = field(
        default_factory=lambda: PurePosixPath("goodnotes-manifest.json")
    )
    maximum_page_bytes: int = _MAX_PAGE_BYTES
    _root_device: int = field(init=False, repr=False)
    _root_inode: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        configured = Path(self.root)
        if configured.is_symlink():
            raise GoodNotesLocalSourceError("the GoodNotes source root cannot be a link")
        try:
            resolved = configured.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise GoodNotesLocalSourceError("the GoodNotes source root is unavailable") from error
        if not resolved.is_dir():
            raise GoodNotesLocalSourceError("the GoodNotes source root must be a directory")
        if not 1 <= self.maximum_page_bytes <= _MAX_PAGE_BYTES:
            raise GoodNotesLocalSourceError("the GoodNotes page bound is invalid")
        _validate_relative_path(self.manifest_relative_path)
        object.__setattr__(self, "root", resolved)
        try:
            descriptor = os.open(resolved, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW)
        except OSError as error:
            raise GoodNotesLocalSourceError("the GoodNotes source root is unavailable") from error
        try:
            metadata = os.fstat(descriptor)
            object.__setattr__(self, "_root_device", metadata.st_dev)
            object.__setattr__(self, "_root_inode", metadata.st_ino)
        finally:
            os.close(descriptor)

    def inventory(self, principal_id: str) -> tuple[SourcePage, ...]:
        """Compatibility materialization for callers that explicitly need it."""
        return tuple(self.stream_inventory(principal_id))

    def stream_inventory(self, principal_id: str) -> Iterator[SourcePage]:
        """Yield one digest-checked page at a time in canonical order."""
        raw_manifest = self._read(self.manifest_relative_path, _MAX_MANIFEST_BYTES)
        try:
            document = json.loads(raw_manifest)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GoodNotesLocalSourceError("the GoodNotes manifest is not valid JSON") from error
        if not isinstance(document, dict) or document.get("schema") != _MANIFEST_SCHEMA:
            raise GoodNotesLocalSourceError("the GoodNotes manifest schema is unsupported")
        entries = document.get("pages")
        if not isinstance(entries, list) or len(entries) > _MAX_PAGES:
            raise GoodNotesLocalSourceError("the GoodNotes manifest page count is invalid")

        selected = [
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("principal_id") == principal_id
        ]
        try:
            selected.sort(
                key=lambda entry: (
                    str(entry["source_object_id"]),
                    int(str(entry["page_number"])),
                    str(entry["source_version_id"]),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise GoodNotesLocalSourceError("the GoodNotes manifest page is invalid") from error
        for entry in selected:
            yield self._page(entry)

    def _page(self, entry: dict[str, object]) -> SourcePage:
        try:
            relative_path = PurePosixPath(str(entry["relative_path"]))
            _validate_relative_path(relative_path)
            media_type = str(entry["media_type"])
            if media_type not in _SUPPORTED_MEDIA_TYPES:
                raise GoodNotesLocalSourceError("the GoodNotes representation type is unsupported")
            content = self._read(relative_path, self.maximum_page_bytes)
            expected_digest = str(entry["content_sha256"])
            if hashlib.sha256(content).hexdigest() != expected_digest:
                raise GoodNotesLocalSourceError("the GoodNotes representation digest changed")
            observed_at = datetime.fromisoformat(str(entry["observed_at"]).replace("Z", "+00:00"))
            return SourcePage(
                principal_id=str(entry["principal_id"]),
                source_id=str(entry["source_id"]),
                source_object_id=str(entry["source_object_id"]),
                source_version_id=str(entry["source_version_id"]),
                page_number=int(str(entry["page_number"])),
                observed_at=observed_at,
                content=content,
                representation_media_type=media_type,
            )
        except GoodNotesLocalSourceError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise GoodNotesLocalSourceError("the GoodNotes manifest page is invalid") from error

    def _read(self, relative_path: PurePosixPath, maximum_bytes: int) -> bytes:
        return _read_admitted(
            self.root, self._root_device, self._root_inode, relative_path, maximum_bytes
        ).content


@dataclass(frozen=True, slots=True)
class NotebookFileObservation:
    """Settled notebook-file metadata. Path is history, not identity."""

    relative_path: str
    size_bytes: int
    sha256: str
    mtime_ns: int
    media_type: str
    content: bytes = field(repr=False)
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class LocalGoodNotesObserver:
    """Bounded notebook-file observer on the same allowlisted root as the manifest source.

    It does not crawl. Callers name explicit relative PDF/image paths, or settle
    the relative paths already admitted by ``ManifestGoodNotesSource``.
    """

    root: Path
    source_root_id: str
    maximum_file_bytes: int = _MAX_PAGE_BYTES
    _root_device: int = field(init=False, repr=False)
    _root_inode: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_root_alias(self.source_root_id)
        configured = Path(self.root)
        if configured.is_symlink():
            raise GoodNotesLocalSourceError("the GoodNotes source root cannot be a link")
        try:
            resolved = configured.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise GoodNotesLocalSourceError("the GoodNotes source root is unavailable") from error
        if not resolved.is_dir():
            raise GoodNotesLocalSourceError("the GoodNotes source root must be a directory")
        if not 1 <= self.maximum_file_bytes <= _MAX_PAGE_BYTES:
            raise GoodNotesLocalSourceError("the GoodNotes page bound is invalid")
        object.__setattr__(self, "root", resolved)
        try:
            descriptor = os.open(resolved, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW)
        except OSError as error:
            raise GoodNotesLocalSourceError("the GoodNotes source root is unavailable") from error
        try:
            metadata = os.fstat(descriptor)
            object.__setattr__(self, "_root_device", metadata.st_dev)
            object.__setattr__(self, "_root_inode", metadata.st_ino)
        finally:
            os.close(descriptor)

    def settle(
        self, relative_path: PurePosixPath, *, page_count: int | None = None
    ) -> NotebookFileObservation:
        """Read twice; fail closed on digest drift or mid-read mutation."""
        _validate_relative_path(relative_path)
        media_type = _SUFFIX_MEDIA_TYPES.get(relative_path.suffix.lower())
        if media_type is None:
            raise GoodNotesLocalSourceError("the GoodNotes representation type is unsupported")
        first = _read_admitted(
            self.root, self._root_device, self._root_inode, relative_path, self.maximum_file_bytes
        )
        second = _read_admitted(
            self.root, self._root_device, self._root_inode, relative_path, self.maximum_file_bytes
        )
        if (
            first.sha256 != second.sha256
            or first.size_bytes != second.size_bytes
            or first.mtime_ns != second.mtime_ns
        ):
            raise GoodNotesLocalSourceError("the GoodNotes representation digest changed")
        return NotebookFileObservation(
            relative_path=str(relative_path),
            size_bytes=second.size_bytes,
            sha256=second.sha256,
            mtime_ns=second.mtime_ns,
            media_type=media_type,
            page_count=page_count,
            content=second.content,
        )

    def observe(
        self,
        relative_paths: tuple[PurePosixPath, ...],
        *,
        page_count: int | None = None,
    ) -> tuple[NotebookFileObservation, ...]:
        if not relative_paths:
            raise GoodNotesLocalSourceError("an explicit GoodNotes path is required")
        return tuple(self.settle(path, page_count=page_count) for path in relative_paths)

    def liveness(
        self,
        relative_path: PurePosixPath,
        *,
        checked_at: datetime,
        maximum_staleness: timedelta,
        previous: GoodNotesSourceLivenessReceipt | None = None,
        acknowledged_reappearance_sha256: str | None = None,
        page_count: int | None = None,
    ) -> GoodNotesSourceLivenessReceipt:
        """Observe one explicit path without turning absence or reappearance into success."""
        _validate_relative_path(relative_path)
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise GoodNotesLocalSourceError("the GoodNotes liveness check time must be aware")
        maximum_staleness_seconds = maximum_staleness.total_seconds()
        if maximum_staleness_seconds <= 0:
            raise GoodNotesLocalSourceError("the GoodNotes liveness interval must be positive")
        path = str(relative_path)
        if previous is not None:
            if previous.source_root_id != self.source_root_id or previous.relative_path != path:
                raise GoodNotesLocalSourceError("the prior GoodNotes liveness binding changed")
            if checked_at < previous.checked_at:
                raise GoodNotesLocalSourceError("the GoodNotes liveness clock moved backwards")
        if acknowledged_reappearance_sha256 is not None:
            if previous is None or previous.state is not GoodNotesSourceLiveness.REAPPEARED:
                raise GoodNotesLocalSourceError(
                    "a GoodNotes reappearance acknowledgment requires a prior reappearance"
                )
            if acknowledged_reappearance_sha256 != previous.current_sha256:
                raise GoodNotesLocalSourceError(
                    "the GoodNotes reappearance acknowledgment digest changed"
                )
        prior_sha256 = None
        if previous is not None:
            prior_sha256 = (
                previous.prior_sha256
                if previous.state is GoodNotesSourceLiveness.REAPPEARED
                else previous.current_sha256 or previous.prior_sha256
            )
        try:
            observation = self.settle(relative_path, page_count=page_count)
        except GoodNotesSourceMissingError:
            last_seen_at = previous.last_seen_at if previous is not None else None
            state = GoodNotesSourceLiveness.MISSING
            if (
                last_seen_at is not None
                and (checked_at - last_seen_at).total_seconds() > maximum_staleness_seconds
            ):
                state = GoodNotesSourceLiveness.STALE
            return GoodNotesSourceLivenessReceipt(
                source_root_id=self.source_root_id,
                relative_path=path,
                state=state,
                checked_at=checked_at,
                maximum_staleness_seconds=maximum_staleness_seconds,
                last_seen_at=last_seen_at,
                current_sha256=None,
                prior_sha256=prior_sha256,
            )
        reappearance_pending = previous is not None and previous.state in {
            GoodNotesSourceLiveness.MISSING,
            GoodNotesSourceLiveness.STALE,
            GoodNotesSourceLiveness.REAPPEARED,
        }
        acknowledged_unchanged = (
            acknowledged_reappearance_sha256 is not None
            and observation.sha256 == acknowledged_reappearance_sha256
        )
        reappeared = reappearance_pending and not acknowledged_unchanged
        state = (
            GoodNotesSourceLiveness.REAPPEARED if reappeared else GoodNotesSourceLiveness.AVAILABLE
        )
        return GoodNotesSourceLivenessReceipt(
            source_root_id=self.source_root_id,
            relative_path=path,
            state=state,
            checked_at=checked_at,
            maximum_staleness_seconds=maximum_staleness_seconds,
            last_seen_at=checked_at,
            current_sha256=observation.sha256,
            prior_sha256=prior_sha256,
            reappeared_content_changed=(
                observation.sha256 != prior_sha256
                if reappeared and prior_sha256 is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class _AdmittedRead:
    content: bytes
    size_bytes: int
    mtime_ns: int
    sha256: str


def _read_admitted(
    root: Path,
    root_device: int,
    root_inode: int,
    relative_path: PurePosixPath,
    maximum_bytes: int,
) -> _AdmittedRead:
    try:
        root_descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW)
    except FileNotFoundError as error:
        raise GoodNotesSourceMissingError("the GoodNotes source path is missing") from error
    except OSError as error:
        raise GoodNotesLocalSourceError("the GoodNotes source root is unavailable") from error
    try:
        root_metadata = os.fstat(root_descriptor)
        if (root_metadata.st_dev, root_metadata.st_ino) != (root_device, root_inode):
            raise GoodNotesLocalSourceError("the GoodNotes source root identity changed")
        parent_descriptor = root_descriptor
        opened_parents: list[int] = []
        try:
            for component in relative_path.parts[:-1]:
                parent_descriptor = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
                    dir_fd=parent_descriptor,
                )
                opened_parents.append(parent_descriptor)
            descriptor = os.open(
                relative_path.parts[-1],
                os.O_RDONLY | os.O_NONBLOCK | _NOFOLLOW,
                dir_fd=parent_descriptor,
            )
            try:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
                    raise GoodNotesLocalSourceError(
                        "the GoodNotes source file is not a bounded file"
                    )
                content = bytearray()
                while len(content) <= maximum_bytes:
                    chunk = os.read(descriptor, min(65_536, maximum_bytes + 1 - len(content)))
                    if not chunk:
                        break
                    content.extend(chunk)
                if len(content) > maximum_bytes:
                    raise GoodNotesLocalSourceError("the GoodNotes source file exceeds its bound")
                after = os.fstat(descriptor)
                if (after.st_size, _mtime_ns(after), after.st_dev, after.st_ino) != (
                    before.st_size,
                    _mtime_ns(before),
                    before.st_dev,
                    before.st_ino,
                ):
                    raise GoodNotesLocalSourceError("the GoodNotes representation digest changed")
                payload = bytes(content)
                return _AdmittedRead(
                    content=payload,
                    size_bytes=len(payload),
                    mtime_ns=_mtime_ns(after),
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            finally:
                os.close(descriptor)
        finally:
            for opened in reversed(opened_parents):
                os.close(opened)
    except FileNotFoundError as error:
        raise GoodNotesSourceMissingError("the GoodNotes source path is missing") from error
    except OSError as error:
        raise GoodNotesLocalSourceError("the GoodNotes source file is unavailable") from error
    finally:
        os.close(root_descriptor)


def _mtime_ns(metadata: os.stat_result) -> int:
    return int(getattr(metadata, "st_mtime_ns", int(metadata.st_mtime * 1_000_000_000)))


def _validate_relative_path(path: PurePosixPath) -> None:
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise GoodNotesLocalSourceError("a bounded relative GoodNotes path is required")


def _validate_root_alias(value: str) -> None:
    if not 1 <= len(value) <= 128 or "\x00" in value or "/" in value:
        raise GoodNotesLocalSourceError("source_root_id is an opaque alias, not a filesystem path")


@dataclass(frozen=True, slots=True)
class BoundedLocalOCRTranscriber:
    """No-shell local OCR command with a closed JSON region result."""

    command: tuple[str, ...]
    name: str
    version: str
    executable_root: Path | None = None
    timeout_seconds: float = 30.0
    maximum_input_bytes: int = _MAX_PAGE_BYTES
    maximum_output_bytes: int = _MAX_OCR_OUTPUT_BYTES
    maximum_regions: int = _MAX_REGIONS

    def __post_init__(self) -> None:
        if not self.command or not Path(self.command[0]).is_absolute():
            raise ValueError("the OCR executable must be an explicit absolute path")
        if self.executable_root is not None and not self.executable_root.is_absolute():
            raise ValueError("the OCR executable root must be an explicit absolute path")
        if not self.name or not self.version:
            raise ValueError("OCR provenance is required")
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("the OCR timeout must be bounded")
        if not 1 <= self.maximum_input_bytes <= _MAX_PAGE_BYTES:
            raise ValueError("the OCR input bound is invalid")
        if not 1 <= self.maximum_output_bytes <= _MAX_OCR_OUTPUT_BYTES:
            raise ValueError("the OCR output bound is invalid")
        if not 1 <= self.maximum_regions <= _MAX_REGIONS:
            raise ValueError("the OCR region bound is invalid")

    def transcribe(
        self, page: SourcePage, *, timeout_seconds: float | None = None
    ) -> tuple[TranscribedRegion, ...]:
        if page.representation_media_type not in _SUPPORTED_MEDIA_TYPES:
            raise GoodNotesTranscriptionError("the page representation is not OCR eligible")
        if len(page.content) > self.maximum_input_bytes:
            raise GoodNotesTranscriptionError("the page representation exceeds the OCR bound")
        argv = (*self._resolved_command(), "--media-type", page.representation_media_type)
        effective_timeout = min(self.timeout_seconds, timeout_seconds or self.timeout_seconds)
        returncode, output, overflowed = self._run_bounded(argv, page.content, effective_timeout)
        if returncode != 0 or overflowed:
            raise GoodNotesTranscriptionError("the local OCR command returned no admissible result")
        try:
            document = json.loads(output)
            regions = document["regions"]
            if not isinstance(regions, list) or len(regions) > self.maximum_regions:
                raise GoodNotesTranscriptionError("the local OCR region count is invalid")
            return tuple(self._region(region) for region in regions)
        except GoodNotesTranscriptionError:
            raise
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GoodNotesTranscriptionError("the local OCR result is invalid") from error

    def _resolved_command(self) -> tuple[str, ...]:
        """Resolve the executable inside its admitted root before every launch."""
        if self.executable_root is None:
            return self.command
        try:
            root = self.executable_root.resolve(strict=True)
            executable = Path(self.command[0]).resolve(strict=True)
        except OSError as error:
            raise GoodNotesTranscriptionError("the local OCR executable is unavailable") from error
        if not executable.is_file() or not executable.is_relative_to(root):
            raise GoodNotesTranscriptionError("the local OCR executable escaped its admitted root")
        return (str(executable), *self.command[1:])

    def _run_bounded(
        self, argv: tuple[str, ...], content: bytes, timeout_seconds: float
    ) -> tuple[int, bytes, bool]:
        try:
            process = subprocess.Popen(  # noqa: S603 - explicit argv, no shell
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin"},
            )
        except OSError as error:
            raise GoodNotesTranscriptionError("the local OCR command did not start") from error
        if process.stdin is None or process.stdout is None:  # pragma: no cover - Popen contract
            process.kill()
            raise GoodNotesTranscriptionError("the local OCR pipes were unavailable")
        stdin = process.stdin
        stdout = process.stdout
        output = bytearray()
        overflowed = threading.Event()

        def write_input() -> None:
            try:
                stdin.write(content)
            except BrokenPipeError:
                pass
            finally:
                stdin.close()

        def read_output() -> None:
            while chunk := stdout.read(65_536):
                remaining = self.maximum_output_bytes + 1 - len(output)
                output.extend(chunk[:remaining])
                if len(output) > self.maximum_output_bytes:
                    overflowed.set()
                    process.kill()
                    break
            stdout.close()

        writer = threading.Thread(target=write_input, daemon=True)
        reader = threading.Thread(target=read_output, daemon=True)
        writer.start()
        reader.start()
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise GoodNotesTranscriptionError("the local OCR command did not complete") from error
        finally:
            writer.join(timeout=1)
            reader.join(timeout=1)
        return returncode, bytes(output), overflowed.is_set()

    @staticmethod
    def _region(value: object) -> TranscribedRegion:
        if not isinstance(value, dict):
            raise GoodNotesTranscriptionError("the local OCR region is invalid")
        try:
            text = value["text"]
            confidence = float(value["confidence"])
            box = value["box"]
            if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
                raise GoodNotesTranscriptionError("the local OCR text is invalid")
            if not isinstance(box, dict) or not 0 <= confidence <= 1:
                raise GoodNotesTranscriptionError("the local OCR region is invalid")
            return TranscribedRegion(
                box=RegionBox(
                    x=float(box["x"]),
                    y=float(box["y"]),
                    width=float(box["width"]),
                    height=float(box["height"]),
                ),
                text=text,
                confidence=confidence,
            )
        except GoodNotesTranscriptionError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise GoodNotesTranscriptionError("the local OCR region is invalid") from error
