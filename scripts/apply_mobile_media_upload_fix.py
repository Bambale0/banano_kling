from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, *, marker: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if marker in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected source block not found in {path}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


UPLOAD_AREA = r"""'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { UploadedFile } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Upload, X, Loader2, Video, Music, Plus } from 'lucide-react'

interface UploadAreaProps {
  files: UploadedFile[]
  onFilesChange: (files: UploadedFile[]) => void
  maxFiles: number
  accept: string
  required?: boolean
  onUpload?: (file: File) => Promise<UploadedFile>
  libraryFiles?: UploadedFile[]
  libraryLabel?: string
}

const MEDIA_MIME_BY_EXTENSION: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  heic: 'image/heic',
  heif: 'image/heif',
  avif: 'image/avif',
  mp4: 'video/mp4',
  mov: 'video/quicktime',
  m4v: 'video/x-m4v',
  webm: 'video/webm',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  m4a: 'audio/mp4',
  aac: 'audio/aac',
  ogg: 'audio/ogg',
}

function normalizedBrowserFile(file: File): File {
  const declaredType = String(file.type || '').toLowerCase()
  if (declaredType && declaredType !== 'application/octet-stream') return file

  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  const inferredType = MEDIA_MIME_BY_EXTENSION[extension]
  if (!inferredType) return file

  return new File([file], file.name, {
    type: inferredType,
    lastModified: file.lastModified,
  })
}

function matchesAcceptedType(file: File, accept: string) {
  const normalized = normalizedBrowserFile(file)
  if (accept.startsWith('image/')) return normalized.type.startsWith('image/')
  if (accept.startsWith('video/')) return normalized.type.startsWith('video/')
  if (accept.startsWith('audio/')) return normalized.type.startsWith('audio/')
  return true
}

export function UploadArea({
  files,
  onFilesChange,
  maxFiles,
  accept,
  required,
  onUpload,
  libraryFiles = [],
  libraryLabel = 'Сохранённые референсы',
}: UploadAreaProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const filesRef = useRef(files)
  const [isDragging, setIsDragging] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  useEffect(() => {
    filesRef.current = files
  }, [files])

  const publishFiles = useCallback((nextFiles: UploadedFile[]) => {
    filesRef.current = nextFiles
    onFilesChange(nextFiles)
  }, [onFilesChange])

  const handleFiles = useCallback(async (fileList: FileList) => {
    setUploadError(null)

    for (const sourceFile of Array.from(fileList)) {
      const file = normalizedBrowserFile(sourceFile)
      const currentFiles = filesRef.current
      if (currentFiles.length >= maxFiles) break
      if (!matchesAcceptedType(file, accept)) {
        setUploadError(
          accept.startsWith('image/')
            ? 'Можно загружать только изображения'
            : accept.startsWith('video/')
              ? 'Можно загружать только видео'
              : 'Можно загружать только аудио'
        )
        continue
      }

      const localUrl = file.type.startsWith('image/') || file.type.startsWith('video/')
        ? URL.createObjectURL(file)
        : ''
      const pendingFile: UploadedFile = {
        id: `file_${Date.now()}_${Math.random().toString(36).slice(2)}`,
        name: file.name,
        url: localUrl,
        type: file.type.startsWith('video/') ? 'video' : file.type.startsWith('audio/') ? 'audio' : 'image',
        size: file.size,
        uploading: true,
      }

      publishFiles([...filesRef.current, pendingFile])

      try {
        const uploadedFile = onUpload
          ? await onUpload(file)
          : {
              ...pendingFile,
              uploading: false,
            }
        const latestFiles = filesRef.current
        const nextFiles = latestFiles.map((item) =>
          item.id === pendingFile.id ? { ...uploadedFile, id: pendingFile.id, uploading: false } : item
        )
        publishFiles(nextFiles)
      } catch (error) {
        publishFiles(filesRef.current.filter((item) => item.id !== pendingFile.id))
        setUploadError(
          error instanceof Error ? error.message : 'Не удалось загрузить файл'
        )
      } finally {
        if (localUrl) URL.revokeObjectURL(localUrl)
      }
    }
  }, [accept, maxFiles, onUpload, publishFiles])

  const handleDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(false)
    void handleFiles(event.dataTransfer.files)
  }, [handleFiles])

  const handleRemove = (id: string) => {
    const removed = filesRef.current.find((file) => file.id === id)
    if (removed?.url.startsWith('blob:')) URL.revokeObjectURL(removed.url)
    publishFiles(filesRef.current.filter((file) => file.id !== id))
  }

  const canUploadMore = files.length < maxFiles
  const availableLibraryFiles = libraryFiles.filter((item) => !files.some((selected) => selected.url === item.url))

  const handleAddFromLibrary = (file: UploadedFile) => {
    if (!canUploadMore) return
    publishFiles([...filesRef.current, { ...file, id: `${file.id}_${Date.now()}` }])
    setUploadError(null)
  }

  return (
    <div className="space-y-3" aria-busy={files.some((file) => file.uploading)}>
      {canUploadMore && (
        <div
          onDragOver={(event) => {
            event.preventDefault()
            setIsDragging(true)
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className={cn(
            'relative flex flex-col items-center justify-center',
            'p-6 rounded-xl border-2 border-dashed cursor-pointer',
            'transition-all duration-200',
            isDragging
              ? 'border-gold bg-gold/5'
              : required
                ? 'border-gold/50 bg-gold/5 hover:border-gold hover:bg-gold/10'
                : 'border-border/50 bg-secondary/30 hover:border-border hover:bg-secondary/50'
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept={accept}
            multiple={maxFiles > 1}
            onChange={(event) => {
              const selectedFiles = event.target.files
              event.target.value = ''
              if (selectedFiles) void handleFiles(selectedFiles)
            }}
            className="sr-only"
          />

          <div className={cn(
            'w-12 h-12 rounded-xl flex items-center justify-center mb-3',
            required ? 'bg-gold/20' : 'bg-secondary/80'
          )}>
            <Upload className={cn('w-6 h-6', required ? 'text-gold' : 'text-muted-foreground')} />
          </div>

          <p className="text-sm text-foreground mb-1">
            {isDragging ? 'Отпустите файлы' : 'Нажмите или перетащите'}
          </p>
          <p className="text-xs text-muted-foreground">
            Макс. {maxFiles} {maxFiles === 1 ? 'файл' : 'файла'}
          </p>
        </div>
      )}

      {availableLibraryFiles.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{libraryLabel}</p>
            <span className="text-[11px] text-muted-foreground">Можно добавить без повторной загрузки</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {availableLibraryFiles.slice(0, Math.max(0, maxFiles - files.length) + 8).map((file) => (
              <button
                key={file.id}
                type="button"
                onClick={() => handleAddFromLibrary(file)}
                className={cn(
                  'inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-all duration-200',
                  'border-border/50 bg-secondary/40 text-foreground hover:border-gold/40 hover:bg-secondary/70'
                )}
              >
                {file.type === 'image' ? (
                  <img src={file.url} alt="" className="h-7 w-7 rounded object-cover" />
                ) : (
                  <div className="flex h-7 w-7 items-center justify-center rounded bg-secondary">
                    {file.type === 'audio' ? (
                      <Music className="h-3.5 w-3.5 text-cyan" />
                    ) : (
                      <Video className="h-3.5 w-3.5 text-cyan" />
                    )}
                  </div>
                )}
                <span className="max-w-[120px] truncate">{file.name}</span>
                <Plus className="h-3.5 w-3.5 text-gold" />
              </button>
            ))}
          </div>
        </div>
      )}

      {files.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {files.map((file) => (
            <div
              key={file.id}
              className={cn(
                'group relative flex items-center gap-2 pl-2 pr-1 py-1 rounded-lg',
                'bg-secondary/80 border border-border/50',
                'transition-all duration-200 hover:border-border'
              )}
            >
              <div className="w-8 h-8 rounded overflow-hidden bg-secondary flex-shrink-0">
                {file.uploading ? (
                  <div className="w-full h-full flex items-center justify-center">
                    <Loader2 className="w-4 h-4 text-muted-foreground animate-spin" />
                  </div>
                ) : file.type === 'image' ? (
                  <img src={file.url} alt="" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    {file.type === 'audio' ? (
                      <Music className="w-4 h-4 text-cyan" />
                    ) : (
                      <Video className="w-4 h-4 text-cyan" />
                    )}
                  </div>
                )}
              </div>

              <span className="text-xs text-foreground max-w-[100px] truncate">
                {file.name}
              </span>

              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation()
                  handleRemove(file.id)
                }}
                className={cn(
                  'w-6 h-6 rounded flex items-center justify-center',
                  'text-muted-foreground hover:text-foreground hover:bg-secondary',
                  'transition-colors'
                )}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {uploadError && (
        <p className="text-xs text-destructive">{uploadError}</p>
      )}

      <p className="text-xs text-muted-foreground">
        {accept.startsWith('image/')
          ? 'PNG, JPG, WEBP, HEIC. Удаляйте лишние референсы прямо из списка.'
          : 'MP3, WAV, M4A или MP4/MOV для видео-референсов. Держите референсы короткими и чистыми.'}
      </p>
    </div>
  )
}
"""

REFERENCE_STORAGE = r'''import hashlib
import logging
import os
from datetime import datetime
from typing import Optional

from bot.config import config
from bot.database import (
    SavedReference,
    get_saved_reference_by_hash,
    save_user_reference,
    touch_saved_references,
)
from bot.services.media_input_utils import (
    image_source_to_provider_safe_png_url,
    resolve_local_upload_path,
)

logger = logging.getLogger(__name__)

REFERENCE_ROOT = os.path.join("static", "uploads", "refs")


def _build_reference_public_url(relative_path: str) -> str:
    return f"{config.static_base_url.rstrip('/')}/uploads/{relative_path.replace(os.sep, '/')}"


def _local_path_for_relative_upload(relative_path: str) -> str:
    return os.path.join("static", "uploads", relative_path)


def _provider_safe_reference_url(file_url: str, kind: str) -> str:
    if kind != "image":
        return file_url
    try:
        safe_url = image_source_to_provider_safe_png_url(file_url)
        return safe_url or file_url
    except Exception:
        logger.exception("Failed to normalize image reference: %s", file_url)
        return file_url


async def save_reference_file(
    telegram_id: int,
    file_bytes: bytes,
    *,
    file_ext: str,
    kind: str = "image",
    original_filename: Optional[str] = None,
    content_type: Optional[str] = None,
    source: str = "telegram",
) -> tuple[Optional[str], Optional[SavedReference]]:
    """Persist reusable reference media outside the ephemeral uploads cleanup path."""
    try:
        if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
            return None, None

        normalized_kind = kind if kind in {"image", "video", "audio"} else "image"
        file_hash = hashlib.sha256(bytes(file_bytes)).hexdigest()
        existing = await get_saved_reference_by_hash(telegram_id, normalized_kind, file_hash)
        if existing:
            local_path = resolve_local_upload_path(existing.file_url)
            if local_path and os.path.exists(local_path):
                public_url = _provider_safe_reference_url(existing.file_url, normalized_kind)
                await touch_saved_references(
                    telegram_id, [existing.file_url], kind=normalized_kind
                )
                return public_url, existing

        safe_ext = (file_ext or "bin").lower().strip(".")
        month = datetime.now().strftime("%Y%m")
        relative_dir = os.path.join("refs", normalized_kind, str(telegram_id), month)
        full_dir = _local_path_for_relative_upload(relative_dir)
        os.makedirs(full_dir, exist_ok=True)

        filename = f"{file_hash[:32]}.{safe_ext}"
        relative_path = os.path.join(relative_dir, filename)
        full_path = _local_path_for_relative_upload(relative_path)

        if not os.path.exists(full_path):
            with open(full_path, "wb") as file_handle:
                file_handle.write(bytes(file_bytes))

        original_public_url = _build_reference_public_url(relative_path)
        public_url = _provider_safe_reference_url(original_public_url, normalized_kind)
        persisted_content_type = (
            "image/png"
            if normalized_kind == "image" and public_url != original_public_url
            else content_type
        )
        saved_reference = await save_user_reference(
            telegram_id,
            kind=normalized_kind,
            file_url=public_url,
            file_hash=file_hash,
            original_filename=original_filename,
            content_type=persisted_content_type,
            source=source,
        )
        return public_url, saved_reference
    except Exception:
        logger.exception("Failed to persist reusable reference for telegram_id=%s", telegram_id)
        return None, None
'''

PHOTO_ANALYSIS_MEDIA = r'''"""Normalize local reference images before sending them to vision providers."""

import base64
import io

from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
except ImportError:  # pragma: no cover - optional on constrained local installs
    register_heif_opener = None

from bot.services.media_input_utils import resolve_local_upload_path

if register_heif_opener is not None:
    register_heif_opener()


def image_source_to_analysis_input(source: str, *, max_edge: int = 2048) -> str:
    """Return a compact data URI for own uploads and leave external URLs untouched."""
    if not isinstance(source, str) or not source or source.startswith("data:image/"):
        return source

    local_path = resolve_local_upload_path(source)
    if not local_path:
        return source

    try:
        with Image.open(local_path) as image:
            normalized = ImageOps.exif_transpose(image).convert("RGB")
            normalized.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            normalized.save(buffer, format="JPEG", quality=90, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        return source
'''

CONTRACT_TEST = r'''from pathlib import Path


def test_mobile_media_upload_contract() -> None:
    miniapp = Path("bot/miniapp.py").read_text(encoding="utf-8")
    api = Path("frontend/miniapp-v0/lib/api.ts").read_text(encoding="utf-8")
    upload_area = Path(
        "frontend/miniapp-v0/components/forms/upload-area.tsx"
    ).read_text(encoding="utf-8")
    workspace = Path(
        "frontend/miniapp-v0/components/workspace-sheet.tsx"
    ).read_text(encoding="utf-8")
    trends = Path(
        "frontend/miniapp-v0/components/tabs/trends-tab.tsx"
    ).read_text(encoding="utf-8")
    photo_service = Path(
        "bot/services/photo_prompt_service.py"
    ).read_text(encoding="utf-8")

    assert "asyncio.wait_for(request.post(), timeout=60)" in miniapp
    assert "_normalize_miniapp_upload_content_type" in miniapp
    assert "application/octet-stream" in miniapp
    assert "MEDIA_UPLOAD_TIMEOUT_MS = 60_000" in api
    assert "normalizedMediaUploadFile" in api
    assert "filesRef.current" in upload_area
    assert "photoUploadAttemptRef" in workspace
    assert "previewUploadAttemptRef" in trends
    assert "image_source_to_analysis_input" in photo_service
'''


def main() -> None:
    Path("frontend/miniapp-v0/components/forms/upload-area.tsx").write_text(
        UPLOAD_AREA,
        encoding="utf-8",
    )
    Path("bot/services/reference_storage_service.py").write_text(
        REFERENCE_STORAGE,
        encoding="utf-8",
    )
    Path("bot/services/photo_analysis_media.py").write_text(
        PHOTO_ANALYSIS_MEDIA,
        encoding="utf-8",
    )
    Path("tests/test_mobile_media_upload_contract.py").write_text(
        CONTRACT_TEST,
        encoding="utf-8",
    )

    replace_once(
        "requirements.txt",
        "Pillow>=10.0.0\n",
        "Pillow>=10.0.0\npillow-heif>=0.18.0,<2\n",
        marker="pillow-heif>=0.18.0,<2",
    )

    miniapp_helper = r'''

def _normalize_miniapp_upload_content_type(
    file_kind: str,
    filename: str,
    content_type: str,
    raw: bytes,
) -> str:
    """Accept iOS WebView uploads with missing/octet-stream MIME after safe sniffing."""
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    config_entry = FILE_KIND_MAP[file_kind]
    expected_prefix = config_entry["prefix"]
    if declared.startswith(expected_prefix):
        return declared

    if declared not in {"", "application/octet-stream", "binary/octet-stream"}:
        return ""

    filename_mime = (mimetypes.guess_type(filename or "")[0] or "").lower()
    if filename_mime.startswith(expected_prefix):
        return filename_mime

    extension = Path(filename or "").suffix.lstrip(".").lower()
    extension_mimes = {
        "heic": "image/heic",
        "heif": "image/heif",
        "avif": "image/avif",
        "mov": "video/quicktime",
        "m4v": "video/x-m4v",
        "m4a": "audio/mp4",
    }
    extension_mime = extension_mimes.get(extension, "")
    if extension_mime.startswith(expected_prefix):
        return extension_mime

    if config_entry["group"] != "image":
        return ""

    try:
        import io  # noqa: PLC0415

        from PIL import Image, UnidentifiedImageError  # noqa: PLC0415

        with Image.open(io.BytesIO(raw)) as image:
            image_format = str(image.format or "").upper()
        return {
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
            "GIF": "image/gif",
            "TIFF": "image/tiff",
            "AVIF": "image/avif",
            "HEIF": "image/heif",
            "HEIC": "image/heic",
        }.get(image_format, "")
    except (OSError, UnidentifiedImageError):
        return ""
'''
    replace_once(
        "bot/miniapp.py",
        'FILE_KIND_MAP = {\n    "image_reference": {"prefix": "image/", "fallback_ext": "png", "group": "image"},\n    "video_reference": {"prefix": "video/", "fallback_ext": "mp4", "group": "video"},\n    "audio_reference": {"prefix": "audio/", "fallback_ext": "mp3", "group": "audio"},\n    "assistant_audio": {"prefix": "audio/", "fallback_ext": "webm", "group": "audio"},\n}\n',
        'FILE_KIND_MAP = {\n    "image_reference": {"prefix": "image/", "fallback_ext": "png", "group": "image"},\n    "video_reference": {"prefix": "video/", "fallback_ext": "mp4", "group": "video"},\n    "audio_reference": {"prefix": "audio/", "fallback_ext": "mp3", "group": "audio"},\n    "assistant_audio": {"prefix": "audio/", "fallback_ext": "webm", "group": "audio"},\n}\n' + miniapp_helper,
        marker="def _normalize_miniapp_upload_content_type(",
    )
    replace_once(
        "bot/miniapp.py",
        '    if isinstance(error, ConnectionResetError):\n',
        '    if isinstance(error, TimeoutError):\n        return web.json_response(\n            {"ok": False, "error": "Загрузка не завершилась за 60 секунд. Попробуйте ещё раз."},\n            status=408,\n        )\n\n    if isinstance(error, ConnectionResetError):\n',
        marker="Загрузка не завершилась за 60 секунд",
    )
    replace_once(
        "bot/miniapp.py",
        '        data = await request.post()\n',
        '        data = await asyncio.wait_for(request.post(), timeout=60)\n',
        marker="asyncio.wait_for(request.post(), timeout=60)",
    )
    replace_once(
        "bot/miniapp.py",
        '''        config_entry = FILE_KIND_MAP[file_kind]
        content_type = getattr(upload, "content_type", "") or ""
        if not content_type.startswith(config_entry["prefix"]):
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Ожидался тип {config_entry['prefix']}*, получен {content_type or 'unknown'}",
                },
                status=400,
            )

        raw = upload.file.read()
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            return web.json_response(
                {"ok": False, "error": "Не удалось прочитать файл"}, status=400
            )
''',
        '''        config_entry = FILE_KIND_MAP[file_kind]
        raw = upload.file.read()
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            return web.json_response(
                {"ok": False, "error": "Не удалось прочитать файл"}, status=400
            )

        content_type = _normalize_miniapp_upload_content_type(
            file_kind,
            getattr(upload, "filename", "") or "",
            getattr(upload, "content_type", "") or "",
            bytes(raw),
        )
        if not content_type:
            declared_type = getattr(upload, "content_type", "") or "unknown"
            return web.json_response(
                {
                    "ok": False,
                    "error": (
                        f"Формат файла не распознан: {declared_type}. "
                        "Используйте JPG, PNG, WEBP, HEIC, MP4 или MOV."
                    ),
                },
                status=400,
            )
''',
        marker="Формат файла не распознан",
    )

    replace_once(
        "bot/services/photo_prompt_service.py",
        "from bot.config import config\n",
        "from bot.config import config\nfrom bot.services.photo_analysis_media import image_source_to_analysis_input\n",
        marker="from bot.services.photo_analysis_media import image_source_to_analysis_input",
    )
    replace_once(
        "bot/services/photo_prompt_service.py",
        '''        image_url = (image_url or "").strip()
        has_image = bool(image_url)
''',
        '''        image_url = (image_url or "").strip()
        if image_url:
            image_url = image_source_to_analysis_input(image_url)
        has_image = bool(image_url)
''',
        marker="image_url = image_source_to_analysis_input(image_url)",
    )

    api_old = '''export async function uploadFile(
  fileKind: 'image_reference' | 'video_reference' | 'audio_reference' | 'assistant_audio',
  file: File
): Promise<UploadedFile> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const formData = new FormData()
  formData.append('init_data', initData)
  formData.append('file_kind', fileKind)
  formData.append('file', file)

  const response = await fetch(`${getApiBasePath()}/upload`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body: formData,
    cache: 'no-store',
    credentials: 'same-origin',
  })
  const data = await parseJson<{
    ok: true
    url: string
    kind: 'image' | 'video' | 'audio'
    filename: string
    reference?: SavedReference | null
  }>(response)

  return {
    id: `file_${Date.now()}_${Math.random().toString(36).slice(2)}`,
    name: data.filename,
    url: data.url,
    type: data.kind,
    size: file.size,
    saved_reference_id: data.reference?.id || null,
    created_at: data.reference?.created_at || null,
    source: data.reference?.source,
  }
}
'''
    api_new = '''const MEDIA_UPLOAD_TIMEOUT_MS = 60_000

const MEDIA_MIME_BY_EXTENSION: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  heic: 'image/heic',
  heif: 'image/heif',
  avif: 'image/avif',
  mp4: 'video/mp4',
  mov: 'video/quicktime',
  m4v: 'video/x-m4v',
  webm: 'video/webm',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  m4a: 'audio/mp4',
  aac: 'audio/aac',
  ogg: 'audio/ogg',
}

function normalizedMediaUploadFile(file: File): File {
  const declaredType = String(file.type || '').toLowerCase()
  if (declaredType && declaredType !== 'application/octet-stream') return file

  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  const inferredType = MEDIA_MIME_BY_EXTENSION[extension]
  if (!inferredType) return file

  return new File([file], file.name, {
    type: inferredType,
    lastModified: file.lastModified,
  })
}

export async function uploadFile(
  fileKind: 'image_reference' | 'video_reference' | 'audio_reference' | 'assistant_audio',
  file: File
): Promise<UploadedFile> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }

  const normalizedFile = normalizedMediaUploadFile(file)
  const formData = new FormData()
  formData.append('init_data', initData)
  formData.append('file_kind', fileKind)
  formData.append('file', normalizedFile)

  const controller = new AbortController()
  const timeoutId = globalThis.setTimeout(() => controller.abort(), MEDIA_UPLOAD_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetch(`${getApiBasePath()}/upload`, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      body: formData,
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Загрузка не завершилась за 60 секунд. Проверьте сеть и повторите.')
    }
    throw error
  } finally {
    globalThis.clearTimeout(timeoutId)
  }

  const data = await parseJson<{
    ok: true
    url: string
    kind: 'image' | 'video' | 'audio'
    filename: string
    reference?: SavedReference | null
  }>(response)

  return {
    id: `file_${Date.now()}_${Math.random().toString(36).slice(2)}`,
    name: data.filename,
    url: data.url,
    type: data.kind,
    size: normalizedFile.size,
    saved_reference_id: data.reference?.id || null,
    created_at: data.reference?.created_at || null,
    source: data.reference?.source,
  }
}
'''
    replace_once(
        "frontend/miniapp-v0/lib/api.ts",
        api_old,
        api_new,
        marker="const MEDIA_UPLOAD_TIMEOUT_MS = 60_000",
    )

    replace_once(
        "frontend/miniapp-v0/components/workspace-sheet.tsx",
        "  const [isAnalyzing, setIsAnalyzing] = useState(false)\n",
        "  const [isAnalyzing, setIsAnalyzing] = useState(false)\n  const photoUploadAttemptRef = useRef(0)\n",
        marker="photoUploadAttemptRef",
    )
    replace_once(
        "frontend/miniapp-v0/components/workspace-sheet.tsx",
        '''  async function handleUpload(file: File) {
    setIsUploading(true)
    setРезультат(null)

    try {
      setPreviewUrl(URL.createObjectURL(file))
      const uploaded = await uploadFile('image_reference', file)
      setReference({
        name: uploaded.name,
        url: uploaded.url,
      })
      toast.success('Фото загружено')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось загрузить фото'
      toast.error('Ошибка загрузки', { description: message })
    } finally {
      setIsUploading(false)
    }
  }
''',
        '''  async function handleUpload(file: File) {
    const attemptId = ++photoUploadAttemptRef.current
    const localPreviewUrl = URL.createObjectURL(file)
    setIsUploading(true)
    setРезультат(null)
    setReference(null)
    setPreviewUrl((current) => {
      if (current?.startsWith('blob:')) URL.revokeObjectURL(current)
      return localPreviewUrl
    })

    try {
      const uploaded = await uploadFile('image_reference', file)
      if (photoUploadAttemptRef.current !== attemptId) return
      setReference({
        name: uploaded.name,
        url: uploaded.url,
      })
      toast.success('Фото загружено')
    } catch (error) {
      if (photoUploadAttemptRef.current !== attemptId) return
      setReference(null)
      setPreviewUrl((current) => current === localPreviewUrl ? null : current)
      const message = error instanceof Error ? error.message : 'Не удалось загрузить фото'
      toast.error('Ошибка загрузки', { description: message })
    } finally {
      if (photoUploadAttemptRef.current === attemptId) setIsUploading(false)
      URL.revokeObjectURL(localPreviewUrl)
    }
  }
''',
        marker="const attemptId = ++photoUploadAttemptRef.current",
    )

    replace_once(
        "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
        "  const fileInputRef = useRef<HTMLInputElement>(null)\n",
        "  const fileInputRef = useRef<HTMLInputElement>(null)\n  const previewUploadAttemptRef = useRef(0)\n",
        marker="previewUploadAttemptRef",
    )
    replace_once(
        "frontend/miniapp-v0/components/tabs/trends-tab.tsx",
        '''  const handlePreviewUpload = async (file?: File) => {
    if (!file) return
    const expectedPrefix = trendKind === 'video' ? 'video/' : 'image/'
    if (!file.type.startsWith(expectedPrefix)) {
      setError(
        trendKind === 'video'
          ? 'Для видео-тренда нужен видеофайл'
          : 'Для фото-тренда нужно изображение',
      )
      return
    }

    setUploadingPreview(true)
    setError(null)
    try {
      const uploaded = await uploadFile(
        trendKind === 'video' ? 'video_reference' : 'image_reference',
        file,
      )
      setPreviewUrl(uploaded.url)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить preview')
    } finally {
      setUploadingPreview(false)
    }
  }
''',
        '''  const handlePreviewUpload = async (file?: File) => {
    if (!file) return
    const expectedPrefix = trendKind === 'video' ? 'video/' : 'image/'
    const extension = file.name.split('.').pop()?.toLowerCase() || ''
    const fallbackExtensions = trendKind === 'video'
      ? new Set(['mp4', 'mov', 'm4v', 'webm'])
      : new Set(['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'avif'])
    if (!file.type.startsWith(expectedPrefix) && !fallbackExtensions.has(extension)) {
      setError(
        trendKind === 'video'
          ? 'Для видео-тренда нужен видеофайл'
          : 'Для фото-тренда нужно изображение',
      )
      return
    }

    const attemptId = ++previewUploadAttemptRef.current
    const localPreviewUrl = URL.createObjectURL(file)
    setUploadingPreview(true)
    setError(null)
    setPreviewUrl((current) => {
      if (current.startsWith('blob:')) URL.revokeObjectURL(current)
      return localPreviewUrl
    })
    try {
      const uploaded = await uploadFile(
        trendKind === 'video' ? 'video_reference' : 'image_reference',
        file,
      )
      if (previewUploadAttemptRef.current !== attemptId) return
      setPreviewUrl(uploaded.url)
    } catch (e) {
      if (previewUploadAttemptRef.current !== attemptId) return
      setPreviewUrl((current) => current === localPreviewUrl ? '' : current)
      setError(e instanceof Error ? e.message : 'Не удалось загрузить preview')
    } finally {
      if (previewUploadAttemptRef.current === attemptId) setUploadingPreview(false)
      URL.revokeObjectURL(localPreviewUrl)
    }
  }
''',
        marker="const attemptId = ++previewUploadAttemptRef.current",
    )

    Path(__file__).unlink()


if __name__ == "__main__":
    main()
