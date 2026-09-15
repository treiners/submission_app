"""Validation and conversion helpers for uploaded report files."""

from pathlib import Path


REPORT_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"}


def classify_report_files(uploaded_files):
    """Classify report uploads as one document or a batch of images."""
    if not uploaded_files:
        raise ValueError("No report files were provided.")

    items = []
    for uploaded_file in uploaded_files:
        filename = str(getattr(uploaded_file, "filename", "") or "").strip()
        if not filename:
            raise ValueError("One or more report files are missing a filename.")
        ext = Path(filename).suffix.lower()
        items.append({"filename": filename, "extension": ext})

    doc_extensions = {".pdf", ".docx"}
    doc_count = sum(1 for item in items if item["extension"] in doc_extensions)
    image_count = sum(1 for item in items if item["extension"] in REPORT_IMAGE_EXTENSIONS)

    if doc_count and image_count:
        raise ValueError("Please upload either a PDF/DOCX report or multiple images, not both.")
    if doc_count:
        if len(items) != 1 or items[0]["extension"] not in doc_extensions:
            raise ValueError("Please upload either a single PDF or a single DOCX report.")
        return {"mode": "single_document", "files": items}
    if image_count:
        if any(item["extension"] not in REPORT_IMAGE_EXTENSIONS for item in items):
            raise ValueError("Report images must be image files only.")
        return {"mode": "image_batch", "files": items}

    invalid = ", ".join(item["filename"] for item in items)
    raise ValueError(f"Unsupported report file type: {invalid}. Please upload PDF, DOCX, or images.")


def convert_report_images_to_pdf(image_paths, output_pdf_path):
    """Convert report images into a centered, one-image-per-page PDF."""
    if not image_paths:
        raise ValueError("No report images were supplied for conversion.")

    try:
        from PIL import Image
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("Image-to-PDF conversion requires Pillow and reportlab packages.") from exc

    page_size = A4
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_canvas = canvas.Canvas(str(output_pdf_path), pagesize=page_size)

    for image_path in image_paths:
        with Image.open(image_path) as image:
            rgb_image = image.convert("RGB")
            width, height = rgb_image.size
            page_width, page_height = page_size
            scale = min(page_width / width, page_height / height)
            draw_width = width * scale
            draw_height = height * scale
            x_offset = (page_width - draw_width) / 2
            y_offset = (page_height - draw_height) / 2
            pdf_canvas.setPageSize(page_size)
            pdf_canvas.drawInlineImage(
                rgb_image,
                x_offset,
                y_offset,
                width=draw_width,
                height=draw_height,
            )
            pdf_canvas.showPage()

    pdf_canvas.save()
