import asyncio
import io
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pypdfium2 as pdfium
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from PIL import Image, ImageChops

from app.core.config import settings

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
GOOGLE_SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
MAX_PDF_BYTES = 20 * 1024 * 1024
# The gateway accepts a 20 MB PNG body; stay below it with room for overhead.
MAX_PNG_BYTES = 18 * 1024 * 1024
MAX_PNG_SHRINK_ATTEMPTS = 3
MAX_IMAGE_WIDTH = 1800
MAX_IMAGE_HEIGHT = 12000
CONTENT_PADDING = 24
PAGE_GAP = 16
WHITE_THRESHOLD = 10


class SheetExportError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class SheetArtifact:
    file_id: str
    file_name: str
    web_view_link: str
    png_data: bytes
    width: int
    height: int


def extract_drive_folder_id(folder_url: str) -> str:
    parsed = urlparse(folder_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
        "drive.google.com",
        "www.drive.google.com",
    }:
        raise SheetExportError(
            "INVALID_DRIVE_FOLDER_URL",
            "Đường dẫn thư mục không phải link Google Drive hợp lệ.",
        )
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", parsed.path)
    if not match:
        raise SheetExportError(
            "INVALID_DRIVE_FOLDER_URL",
            "Không tìm thấy mã thư mục trong đường dẫn Google Drive.",
        )
    return match.group(1)


def crop_white_margins(
    image: Image.Image,
    *,
    padding: int = CONTENT_PADDING,
) -> Image.Image:
    background = Image.new("RGB", image.size, "white")
    difference = ImageChops.difference(image.convert("RGB"), background).convert("L")
    mask = difference.point(lambda value: 255 if value > WHITE_THRESHOLD else 0)
    bbox = mask.getbbox()
    background.close()
    difference.close()
    mask.close()
    if bbox is None:
        return image

    left, top, right, bottom = bbox
    expanded = (
        max(0, left - padding),
        max(0, top - padding),
        min(image.width, right + padding),
        min(image.height, bottom + padding),
    )
    if expanded == (0, 0, image.width, image.height):
        return image
    return image.crop(expanded)


def render_pdf_to_png(pdf_data: bytes) -> tuple[bytes, int, int]:
    try:
        document = pdfium.PdfDocument(pdf_data)
    except Exception as exc:
        raise SheetExportError("SHEET_PDF_INVALID", "Google trả về file PDF không hợp lệ.") from exc
    if len(document) == 0:
        document.close()
        raise SheetExportError("SHEET_PDF_EMPTY", "Tab đầu tiên không tạo được trang PDF nào.")

    pages: list[Image.Image] = []
    try:
        for page_index in range(len(document)):
            page = document[page_index]
            image = page.render(scale=2.0).to_pil().convert("RGB")
            page.close()
            cropped = crop_white_margins(image)
            if cropped is not image:
                image.close()
            pages.append(cropped)
    finally:
        document.close()

    widest = max(image.width for image in pages)
    total_height = sum(image.height for image in pages) + PAGE_GAP * (len(pages) - 1)
    scale = min(1.0, MAX_IMAGE_WIDTH / widest, MAX_IMAGE_HEIGHT / total_height)
    if scale < 1.0:
        resized: list[Image.Image] = []
        for image in pages:
            resized.append(
                image.resize(
                    (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            )
            image.close()
        pages = resized

    width = max(image.width for image in pages)
    height = sum(image.height for image in pages) + PAGE_GAP * (len(pages) - 1)
    combined = Image.new("RGB", (width, height), "white")
    offset = 0
    for image in pages:
        combined.paste(image, ((width - image.width) // 2, offset))
        offset += image.height + PAGE_GAP
        image.close()

    try:
        return encode_png_within_limit(combined)
    finally:
        combined.close()


def encode_png_within_limit(image: Image.Image) -> tuple[bytes, int, int]:
    """Encode to PNG, shrinking until it fits what the gateway will accept.

    A dense sheet can render past the upload limit; without this the send fails
    with a 413 on every retry until the run is marked permanently failed.
    """
    current = image
    try:
        for _ in range(MAX_PNG_SHRINK_ATTEMPTS + 1):
            output = io.BytesIO()
            current.save(output, format="PNG", optimize=True)
            data = output.getvalue()
            if len(data) <= MAX_PNG_BYTES:
                return data, current.width, current.height
            # Encoded size tracks pixel count, so scale each side by the square root.
            ratio = (MAX_PNG_BYTES / len(data)) ** 0.5 * 0.95
            next_size = (
                max(1, round(current.width * ratio)),
                max(1, round(current.height * ratio)),
            )
            if next_size == (current.width, current.height):
                break
            resized = current.resize(next_size, Image.Resampling.LANCZOS)
            if current is not image:
                current.close()
            current = resized
        raise SheetExportError(
            "SHEET_IMAGE_TOO_LARGE",
            "Ảnh công nợ vẫn vượt giới hạn 20 MB sau khi đã giảm kích thước.",
        )
    finally:
        if current is not image:
            current.close()


class GoogleSheetsService:
    def __init__(self) -> None:
        self._credentials: service_account.Credentials | None = None
        self._credential_path: str | None = None
        self._token_lock = asyncio.Lock()

    async def _access_token(self) -> str:
        credential_path = settings.google_service_account_file
        if not credential_path or not Path(credential_path).is_file():
            raise SheetExportError(
                "GOOGLE_DRIVE_NOT_CONFIGURED",
                "Chưa cấu hình Google Service Account cho hệ thống.",
            )
        async with self._token_lock:
            if self._credentials is None or self._credential_path != credential_path:
                try:
                    self._credentials = service_account.Credentials.from_service_account_file(
                        credential_path,
                        scopes=[DRIVE_READONLY_SCOPE, SHEETS_READONLY_SCOPE],
                    )
                except Exception as exc:
                    raise SheetExportError(
                        "GOOGLE_CREDENTIALS_INVALID",
                        "Google Service Account credential không hợp lệ.",
                    ) from exc
                self._credential_path = credential_path
            if not self._credentials.valid or not self._credentials.token:
                try:
                    await asyncio.to_thread(self._credentials.refresh, Request())
                except Exception as exc:
                    raise SheetExportError(
                        "GOOGLE_AUTH_FAILED",
                        "Không thể đăng nhập Google bằng Service Account.",
                    ) from exc
            return str(self._credentials.token)

    async def _get_json(
        self, client: httpx.AsyncClient, url: str, token: str, **params: str | int | bool
    ) -> dict:
        response = await client.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.is_error:
            self._raise_google_error(response)
        try:
            return response.json()
        except ValueError as exc:
            raise SheetExportError(
                "GOOGLE_RESPONSE_INVALID", "Google API trả về dữ liệu không hợp lệ."
            ) from exc

    @staticmethod
    def _raise_google_error(response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise SheetExportError(
                "GOOGLE_DRIVE_ACCESS_DENIED",
                "Service Account chưa có quyền xem thư mục hoặc Google Sheet.",
            )
        if response.status_code == 404:
            raise SheetExportError(
                "GOOGLE_DRIVE_NOT_FOUND", "Không tìm thấy thư mục hoặc Google Sheet."
            )
        raise SheetExportError(
            "GOOGLE_API_ERROR", f"Google API gặp lỗi HTTP {response.status_code}."
        )

    async def export_first_sheet(self, folder_url: str) -> SheetArtifact:
        folder_id = extract_drive_folder_id(folder_url)
        token = await self._access_token()
        timeout = httpx.Timeout(settings.google_api_timeout_seconds, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            file_list = await self._get_json(
                client,
                "https://www.googleapis.com/drive/v3/files",
                token,
                q=(
                    f"'{folder_id}' in parents and trashed = false and "
                    f"mimeType = '{GOOGLE_SHEET_MIME_TYPE}'"
                ),
                orderBy="name",
                pageSize=1,
                fields="files(id,name,webViewLink)",
                spaces="drive",
                supportsAllDrives="true",
                includeItemsFromAllDrives="true",
            )
            files = file_list.get("files") or []
            if not files:
                raise SheetExportError(
                    "GOOGLE_SHEET_NOT_FOUND",
                    "Không tìm thấy file Google Sheets nào trong thư mục khách hàng.",
                )
            sheet_file = files[0]
            file_id = str(sheet_file.get("id") or "")
            file_name = str(sheet_file.get("name") or "Google Sheet")
            web_view_link = str(
                sheet_file.get("webViewLink")
                or f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
            )

            spreadsheet = await self._get_json(
                client,
                f"https://sheets.googleapis.com/v4/spreadsheets/{file_id}",
                token,
                fields="sheets(properties(sheetId,index,title))",
            )
            sheets = spreadsheet.get("sheets") or []
            if not sheets:
                raise SheetExportError(
                    "GOOGLE_SHEET_EMPTY", "Google Sheet không có tab dữ liệu nào."
                )
            first_sheet = min(
                sheets,
                key=lambda item: int(item.get("properties", {}).get("index", 0)),
            )
            sheet_id = first_sheet.get("properties", {}).get("sheetId")
            if sheet_id is None:
                raise SheetExportError(
                    "GOOGLE_SHEET_INVALID", "Không lấy được mã tab đầu tiên của Google Sheet."
                )

            response = await client.get(
                f"https://docs.google.com/spreadsheets/d/{file_id}/export",
                params={
                    "format": "pdf",
                    "gid": str(sheet_id),
                    "size": "A4",
                    "portrait": "true",
                    "fitw": "true",
                    "gridlines": "false",
                    "printtitle": "false",
                    "sheetnames": "false",
                    "pagenum": "UNDEFINED",
                    "attachment": "true",
                    "fzr": "true",
                    "top_margin": "0.35",
                    "bottom_margin": "0.35",
                    "left_margin": "0.35",
                    "right_margin": "0.35",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.is_error:
                self._raise_google_error(response)
            if len(response.content) > MAX_PDF_BYTES:
                raise SheetExportError(
                    "SHEET_PDF_TOO_LARGE", "File PDF của tab đầu tiên vượt quá 20 MB."
                )
            if not response.content.startswith(b"%PDF"):
                raise SheetExportError(
                    "SHEET_PDF_INVALID", "Google không xuất được tab đầu tiên thành PDF."
                )

        png_data, width, height = render_pdf_to_png(response.content)
        return SheetArtifact(
            file_id=file_id,
            file_name=file_name,
            web_view_link=web_view_link,
            png_data=png_data,
            width=width,
            height=height,
        )


google_sheets = GoogleSheetsService()
