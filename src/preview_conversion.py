"""Document and video conversion helpers used by marking previews."""

import hashlib
import shutil
import subprocess
from pathlib import Path

from werkzeug.utils import secure_filename


def resolve_docx_pdf_converter(preferred=None, default="auto"):
    """Choose an available DOCX-to-PDF converter from the configured preference."""
    converter = str(preferred or default or "auto").strip().lower()
    if converter not in {"auto", "libreoffice", "docx2pdf", "dxpdf"}:
        converter = "auto"

    if converter == "auto":
        if shutil.which("soffice") or shutil.which("libreoffice"):
            return "libreoffice"
        try:
            import dxpdf  # noqa: F401
        except ImportError:
            return "docx2pdf"
        return "dxpdf"

    return converter


def _preview_output_path(metadata_folder, relative_path, source_path, directory_name, extension):
    if not metadata_folder:
        return None

    preview_dir = metadata_folder / directory_name
    preview_dir.mkdir(parents=True, exist_ok=True)

    source_stat = source_path.stat()
    source_signature = f"{relative_path}|{int(source_stat.st_mtime)}|{source_stat.st_size}"
    digest = hashlib.sha1(source_signature.encode("utf-8")).hexdigest()[:12]
    base_name = secure_filename(Path(relative_path).stem) or "preview"
    return preview_dir / f"{base_name}_{digest}{extension}"


def docx_pdf_preview_output_path(metadata_folder, relative_path, source_path, directory_name):
    """Return the cache path for a DOCX PDF preview."""
    return _preview_output_path(metadata_folder, relative_path, source_path, directory_name, ".pdf")


def video_preview_output_path(metadata_folder, relative_path, source_path, directory_name):
    """Return the cache path for a video MP4 preview."""
    return _preview_output_path(metadata_folder, relative_path, source_path, directory_name, ".mp4")


def convert_docx_to_pdf_with_docx2pdf(source_docx, target_pdf):
    """Convert a DOCX file with the macOS/Word-backed docx2pdf package."""
    try:
        from docx2pdf import convert as docx2pdf_convert
    except ImportError as error:
        raise RuntimeError(
            "docx2pdf is required for DOCX-to-PDF preview conversion. "
            "Install dependencies from requirements.txt."
        ) from error

    try:
        docx2pdf_convert(str(source_docx.resolve()), str(target_pdf.resolve()))
    except Exception as error:
        raise RuntimeError(
            "docx2pdf conversion failed. On macOS this usually requires Microsoft Word to be installed and available. "
            f"({error})"
        ) from error

    if not target_pdf.exists() or target_pdf.stat().st_size == 0:
        raise RuntimeError("docx2pdf did not produce a valid PDF output.")


def convert_docx_to_pdf_with_dxpdf(source_docx, target_pdf):
    """Convert a DOCX file with the dxpdf package."""
    try:
        import dxpdf
    except ImportError as error:
        raise RuntimeError(
            "dxpdf is required for DOCX-to-PDF preview conversion. "
            "Install dependencies from requirements.txt."
        ) from error

    try:
        dxpdf.convert_file(str(source_docx.resolve()), str(target_pdf.resolve()))
    except Exception as error:
        raise RuntimeError(f"dxpdf conversion failed: {error}") from error

    if not target_pdf.exists() or target_pdf.stat().st_size == 0:
        raise RuntimeError("dxpdf did not produce a valid PDF output.")


def convert_docx_to_pdf_with_libreoffice(source_docx, target_pdf):
    """Convert a DOCX file with a headless LibreOffice installation."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice is not installed or not available on PATH.")

    output_dir = target_pdf.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        soffice,
        "--headless",
        "--nologo",
        "--nolockcheck",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source_docx),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"LibreOffice conversion failed: {completed.stderr.strip() or completed.stdout.strip() or 'unknown error'}"
        )

    produced_pdf = output_dir / f"{source_docx.stem}.pdf"
    if produced_pdf.exists() and produced_pdf != target_pdf:
        if target_pdf.exists():
            try:
                target_pdf.unlink()
            except OSError:
                pass
        produced_pdf.replace(target_pdf)

    if not target_pdf.exists() or target_pdf.stat().st_size == 0:
        raise RuntimeError("LibreOffice did not produce a valid PDF output.")


def convert_docx_to_pdf(source_docx, target_pdf, converter=None, default_converter="auto"):
    """Convert DOCX to PDF using the selected available converter."""
    resolved = resolve_docx_pdf_converter(converter, default_converter)
    if resolved == "libreoffice":
        return convert_docx_to_pdf_with_libreoffice(source_docx, target_pdf)
    if resolved == "docx2pdf":
        return convert_docx_to_pdf_with_docx2pdf(source_docx, target_pdf)
    if resolved == "dxpdf":
        return convert_docx_to_pdf_with_dxpdf(source_docx, target_pdf)
    raise RuntimeError(f"Unsupported DOCX-to-PDF converter: {resolved}")


def ensure_docx_pdf_preview(
    metadata_folder,
    relative_path,
    source_path,
    directory_name,
    converter=None,
    default_converter="auto",
):
    """Create or reuse a cached DOCX PDF preview."""
    output_path = docx_pdf_preview_output_path(
        metadata_folder, relative_path, source_path, directory_name
    )
    if not output_path:
        raise RuntimeError("Could not determine metadata folder for PDF preview output.")

    if output_path.exists():
        return output_path

    temp_output = output_path.with_suffix(".tmp.pdf")
    if temp_output.exists():
        try:
            temp_output.unlink()
        except OSError:
            pass

    convert_docx_to_pdf(source_path, temp_output, converter, default_converter)
    temp_output.replace(output_path)
    return output_path


def convert_video_to_mp4_with_ffmpeg(source_video, target_mp4):
    """Convert a video file to a browser-friendly MP4 with ffmpeg."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise RuntimeError(
            "ffmpeg is required for video fallback conversion. Install ffmpeg and restart the app."
        )

    output_dir = target_mp4.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(source_video),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(target_mp4),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "unknown ffmpeg error"
        raise RuntimeError(f"ffmpeg conversion failed: {details}")

    if not target_mp4.exists() or target_mp4.stat().st_size == 0:
        raise RuntimeError("ffmpeg did not produce a valid MP4 output.")


def ensure_video_mp4_preview(metadata_folder, relative_path, source_path, directory_name):
    """Create or reuse a cached MP4 preview."""
    output_path = video_preview_output_path(
        metadata_folder, relative_path, source_path, directory_name
    )
    if not output_path:
        raise RuntimeError("Could not determine metadata folder for video preview output.")

    if output_path.exists():
        return output_path

    temp_output = output_path.with_suffix(".tmp.mp4")
    if temp_output.exists():
        try:
            temp_output.unlink()
        except OSError:
            pass

    convert_video_to_mp4_with_ffmpeg(source_path, temp_output)
    temp_output.replace(output_path)
    return output_path
