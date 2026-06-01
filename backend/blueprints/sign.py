import io
import re

import fitz
from flask import Blueprint, request

from utils.helpers import error, send_file_and_cleanup
from utils.validators import validate_uploaded_file, validate_pdf_file

sign_bp = Blueprint('sign', __name__)

_ALLOWED_POSITIONS = {
    'bottom-right',
    'bottom-left',
    'top-right',
    'top-left',
    'center',
}


def _parse_font_size():
    raw = request.form.get('fontSize', request.form.get('font_size', '14'))
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return None, error('fontSize must be an integer', 400)

    if size < 1 or size > 200:
        return None, error('fontSize must be between 1 and 200', 400)
    return size, None


def _parse_color():
    color_hex = request.form.get('color', '#000099').strip()
    if not color_hex:
        color_hex = '#000099'

    normalized = color_hex.lstrip('#')
    if not re.fullmatch(r'[0-9a-fA-F]{6}', normalized):
        return None, error('color must be a valid 6-digit hex value', 400)

    return tuple(int(normalized[i:i + 2], 16) / 255 for i in (0, 2, 4)), None


def _get_signature_rect(page, position):
    width = page.rect.width
    height = page.rect.height
    box_width = min(max(width * 0.35, 180), width - 40)
    box_height = 44
    margin = 20

    rects = {
        'bottom-right': fitz.Rect(width - box_width - margin, height - box_height - margin, width - margin, height - margin),
        'bottom-left': fitz.Rect(margin, height - box_height - margin, margin + box_width, height - margin),
        'top-right': fitz.Rect(width - box_width - margin, margin, width - margin, margin + box_height),
        'top-left': fitz.Rect(margin, margin, margin + box_width, margin + box_height),
        'center': fitz.Rect((width - box_width) / 2, (height - box_height) / 2, (width + box_width) / 2, (height + box_height) / 2),
    }
    return rects[position]


@sign_bp.route('/sign/signPdf', methods=['POST'])
def sign_pdf():
    file, filename, upload_err = validate_uploaded_file(request, 'file')
    if upload_err:
        return upload_err

    pdf_err = validate_pdf_file(filename)
    if pdf_err:
        return pdf_err

    signature_text = request.form.get('signature', '').strip()
    if not signature_text:
        return error('Signature text is required', 400)

    position = request.form.get('position', 'bottom-right')
    if position not in _ALLOWED_POSITIONS:
        return error('position must be one of: bottom-right, bottom-left, top-right, top-left, center', 400)

    font_size, font_err = _parse_font_size()
    if font_err:
        return font_err

    color_rgb, color_err = _parse_color()
    if color_err:
        return color_err

    pdf_bytes = file.read()
    if not pdf_bytes:
        return error('Empty PDF file', 400)

    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        if doc.page_count == 0:
            return error('PDF has no pages', 400)

        page = doc[-1]
        page.insert_textbox(
            _get_signature_rect(page, position),
            signature_text,
            fontsize=font_size,
            color=color_rgb,
            align=fitz.TEXT_ALIGN_CENTER,
        )

        out = io.BytesIO()
        doc.save(out)
        out.seek(0)
        return send_file_and_cleanup(
            out.getvalue(),
            mimetype='application/pdf',
            as_attachment=True,
            download_name='signed.pdf',
        )
    except Exception as exc:
        return error(f'Failed to sign PDF: {str(exc)}', 500)
    finally:
        if doc is not None:
            doc.close()
