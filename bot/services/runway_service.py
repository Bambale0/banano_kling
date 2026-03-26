"""
RunwayML Gen-4.5 Service via Replicate API

Model: runwayml/gen-4.5
Docs: runway.md
"""

import asyncio
import base64
import hashlib
import io as _io
import json
import logging
import os
from typing import Any, Dict, List, Optional

import replicate
from dotenv import load_dotenv
from PIL import Image

from bot.config import config

# Load environment variables from .env when running locally/tests
load_dotenv()
logger = logging.getLogger(__name__)

# Persistent store for saved characters/references. This file contains a
# mapping of character_id -> {name, refs: [data_uri_or_url], tags: [...]}
CHARACTER_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "runway_characters.json",
)


def _ensure_character_db():
    parent = os.path.dirname(CHARACTER_DB_PATH)
    if not os.path.exists(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception:
            logger.exception("Failed to create data directory for character DB")
    if not os.path.exists(CHARACTER_DB_PATH):
        try:
            with open(CHARACTER_DB_PATH, "w", encoding="utf-8") as fh:
                json.dump({}, fh)
        except Exception:
            logger.exception("Failed to initialize character DB file")


def _load_character_db() -> Dict[str, Any]:
    _ensure_character_db()
    try:
        with open(CHARACTER_DB_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        logger.exception("Failed to load character DB")
        return {}


def _save_character_db(db: Dict[str, Any]) -> None:
    try:
        with open(CHARACTER_DB_PATH, "w", encoding="utf-8") as fh:
            json.dump(db, fh, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to save character DB")


def _bytes_to_data_uri(b: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(b).decode('utf-8')}"


def _center_crop_data_uri(b: bytes, frac: float = 0.6) -> Optional[str]:
    """Return a data URI for a centered square crop of the image bytes.

    This is a cheap heuristic to produce a "frontal" crop when no face
    detector is available — many user photos are centered on the face.
    frac controls the fraction of the smaller image dimension to keep.
    """
    try:
        img = Image.open(_io.BytesIO(b)).convert("RGB")
        w, h = img.size
        side = int(min(w, h) * frac)
        left = max(0, (w - side) // 2)
        top = max(0, (h - side) // 2)
        crop = img.crop((left, top, left + side, top + side))
        # Optionally we can resize to a standard size — keep original for now
        buf = _io.BytesIO()
        crop.save(buf, format="PNG")
        return (
            f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"
        )
    except Exception:
        logger.exception("Failed to create center-crop frontal image")
        return None


def _face_crop_data_uri(b: bytes, margin: float = 0.25) -> Optional[str]:
    """Attempt to detect a face and return a cropped frontal data URI.

    This function tries to import face_recognition (dlib-backed). If the
    library is available it will attempt to detect the largest face and
    crop around it with a margin. If detection fails or library is absent,
    returns None.
    """
    try:
        import face_recognition

        img = face_recognition.load_image_file(_io.BytesIO(b))
        faces = face_recognition.face_locations(img, model="hog")
        if not faces:
            return None
        # Choose the largest face (by area)
        best = max(faces, key=lambda f: (f[2] - f[0]) * (f[1] - f[3]))
        top, right, bottom, left = best
        h = bottom - top
        w = right - left
        # Expand box by margin (fraction of max dimension)
        pad = int(max(w, h) * margin)
        top = max(0, top - pad)
        left = max(0, left - pad)
        bottom = bottom + pad
        right = right + pad

        pil = Image.open(_io.BytesIO(b)).convert("RGB")
        crop = pil.crop((left, top, right, bottom))
        buf = _io.BytesIO()
        crop.save(buf, format="PNG")
        return (
            f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"
        )
    except Exception:
        # Do not spam logs for missing optional dependency; only log on detection errors
        logger.debug("face_recognition not available or face detection failed")
        return None


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# Ensure DB file exists on import
_ensure_character_db()


class RunwayService:
    """Сервис для работы с RunwayML Gen-4.5 через Replicate API"""

    MODEL_VERSION = "runwayml/gen-4.5"

    ASPECT_RATIOS = ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"]
    DURATIONS = [5, 10]

    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token or config.REPLICATE_API_TOKEN
        # Initialize a dedicated Replicate client instance so we don't depend
        # on module-level global state. This makes behavior deterministic and
        # easier to mock in tests.
        try:
            if self.api_token:
                self.client = replicate.Client(api_token=self.api_token)
            else:
                # If no token provided, create default client which will
                # read from environment variables if available.
                self.client = replicate.Client()
        except Exception:
            # Fallback to module-level usage if client construction fails.
            # Keep a reference for backwards compatibility.
            logger.exception(
                "Failed to initialize Replicate client, falling back to module-level client"
            )
            self.client = None

    # ---------- Character / reference persistence API ----------
    def save_character(
        self,
        name: str,
        reference_image_urls: Optional[List[str]] = None,
        reference_images: Optional[List[bytes]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Save a named character with reference images.

        reference_images may be raw bytes (PNG/JPEG). Stored refs are kept as
        data URIs (for bytes) or raw URLs. Returns the generated character id.
        """
        db = _load_character_db()
        # Normalize refs to data URIs or strings
        refs: List[str] = []
        if reference_images:
            for b in reference_images:
                if isinstance(b, (bytes, bytearray)):
                    refs.append(_bytes_to_data_uri(bytes(b)))
        if reference_image_urls:
            for u in reference_image_urls:
                refs.append(u)

        # Create a stable id from name + refs
        digest = hashlib.sha1((name + "|" + ",".join(refs)).encode("utf-8")).hexdigest()
        char_id = f"ch_{digest[:16]}"
        db[char_id] = {"id": char_id, "name": name, "refs": refs, "tags": tags or []}
        _save_character_db(db)
        logger.info(f"Saved character {char_id} name={name} refs={len(refs)}")
        return char_id

    def get_character(self, char_id: str) -> Optional[Dict[str, Any]]:
        db = _load_character_db()
        return db.get(char_id)

    def list_characters(self) -> List[Dict[str, Any]]:
        db = _load_character_db()
        return list(db.values())

    def delete_character(self, char_id: str) -> bool:
        db = _load_character_db()
        if char_id in db:
            del db[char_id]
            _save_character_db(db)
            logger.info(f"Deleted character {char_id}")
            return True
        return False

    def _load_character_refs(self, char_id: str) -> List[str]:
        ch = self.get_character(char_id)
        if not ch:
            return []
        return ch.get("refs", [])

    async def generate_video(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        reference_images: Optional[List[bytes]] = None,
        character_id: Optional[str] = None,
        seed: Optional[int] = None,
        webhook_url: Optional[str] = None,
        preserve_identity: bool = True,
        strict_preserve_identity: bool = False,
    ) -> Optional[Dict]:
        """Генерация видео text-to-video или image-to-video"""
        duration = max(5, min(duration, 10))
        aspect_ratio = aspect_ratio if aspect_ratio in self.ASPECT_RATIOS else "16:9"
        # By default we attempt to preserve face identity when references are
        # provided. We primarily rely on the elements/frontal_image_url to
        # convey identity-preservation, but some models benefit if a short
        # instruction is provided in the same language as the user's prompt.
        # To avoid language mixing and duplication we add a one-line prefix
        # only when preserve_identity is True and the prompt doesn't already
        # include a preservation instruction.
        # If strict_preserve_identity is requested, prefer that behavior
        # (stronger signals to the API) but do not modify the user's prompt.
        if preserve_identity and not strict_preserve_identity:
            try:
                low = prompt.lower() if prompt else ""
                if (
                    "preserve" not in low
                    and "сохран" not in low
                    and "использ" not in low
                ):
                    # Detect Cyrillic presence to keep instruction in user's language
                    def _has_cyrillic(s: str) -> bool:
                        return any("\u0400" <= ch <= "\u04FF" for ch in s)

                    if _has_cyrillic(prompt or ""):
                        instr = "Используйте предоставленные референсы как отправную точку и сохраните идентичность лица."
                    else:
                        instr = "Use the provided references as the starting point and preserve facial identity."
                    prompt = f"{instr} {prompt}" if prompt else instr
            except Exception:
                logger.exception(
                    "Failed to prepend identity-preservation instruction to prompt"
                )

        input_data = {
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
        }

        # Preserve face/identity when the caller supplies reference imagery.
        # Runway Gen-4.5 only accepts a single initial image, so we prefer the
        # explicit start image, then fall back to the first reference image.
        refs_combined: List[Any] = []

        # If a saved character_id is provided, prefer its stored refs first
        if character_id:
            try:
                saved = self._load_character_refs(character_id)
                if saved:
                    refs_combined.extend(saved)
            except Exception:
                logger.exception(f"Failed to load character refs for {character_id}")

        # then include any explicitly provided images/urls
        if reference_images:
            refs_combined.extend(reference_images)
        if reference_image_urls:
            refs_combined.extend(reference_image_urls)

        if not image_url and refs_combined:
            # If the first ref is bytes, convert to data URI for the 'image' field
            first = refs_combined[0]
            if isinstance(first, (bytes, bytearray)):
                image_url = (
                    f"data:image/png;base64,{base64.b64encode(first).decode('utf-8')}"
                )
            else:
                image_url = first

        if image_url:
            input_data["image"] = image_url
            # Always mark the start image as the primary frontal reference (img1).
            # Per request, we send img1 as the identity anchor with face_preservation=100
            # so the API receives a clear, unambiguous instruction to preserve this face.
            initial_frontal_candidate = image_url

        # Try to derive a frontal crop from the provided start image URL
        # (if it's a local static URL) or data URI. This helps provide a
        # strong frontal_image_url for elements so Runway preserves faces
        # better. frontal_from_image is a data URI or None.
        frontal_from_image: Optional[str] = None
        try:
            if image_url and image_url.startswith("data:image/"):
                # already a data URI — attempt to create a centered crop
                # by decoding the base64 payload
                header, payload = image_url.split(",", 1)
                img_bytes = base64.b64decode(payload)
                frontal_from_image = _face_crop_data_uri(
                    img_bytes
                ) or _center_crop_data_uri(img_bytes)
            elif (
                image_url
                and config.static_base_url
                and image_url.startswith(config.static_base_url)
            ):
                # map public URL back to local static path
                local_path = image_url.replace(config.static_base_url, "static").lstrip(
                    "/"
                )
                if os.path.exists(local_path):
                    with open(local_path, "rb") as fh:
                        img_bytes = fh.read()
                    frontal_from_image = _face_crop_data_uri(
                        img_bytes
                    ) or _center_crop_data_uri(img_bytes)
        except Exception:
            logger.exception("Failed to derive frontal_from_image from image_url")

        # If we have a frontal crop but no other refs, still add an elements
        # entry so the model receives an explicit frontal reference by default.
        # This ensures "preserve_identity=True" leads to maximal preservation
        # even when the caller only provided a start image.
        if frontal_from_image and not refs_combined:
            elements = [
                {
                    "reference_image_urls": [image_url] if image_url else [],
                    "frontal_image_url": frontal_from_image,
                    # Strong signal to preserve this face exactly
                    "face_preservation": 100,
                }
            ]
            input_data["elements"] = elements

            # Also provide a generic "references" array (ImageReference objects)
            # as some Runway endpoints/models honor this field to treat images
            # as style/content references. Include URIs only (strings).
            try:
                refs_for_api = []
                for el in elements:
                    for uri in el.get("reference_image_urls", []):
                        if uri:
                            refs_for_api.append({"type": "image", "uri": uri})
                if refs_for_api:
                    input_data["references"] = refs_for_api
            except Exception:
                logger.debug("Failed to build input_data['references']")

        # If reference images provided, build elements to help preserve
        # identity/face consistency. Convert any bytes to data URIs so the
        # Replicate input contains strings only.
        if refs_combined:

            def _maybe_data_uri(v):
                if isinstance(v, (bytes, bytearray)):
                    return (
                        f"data:image/png;base64,{base64.b64encode(v).decode('utf-8')}"
                    )
                return v

            # Build elements. Two modes:
            # - strict_preserve_identity: set frontal_image_url == ref for
            #   each provided reference (strong signal to preserve identity).
            # - default: use a single frontal anchor (frontal_from_image if
            #   available; otherwise the first ref) and add other refs as
            #   normal reference_image_urls to give context without over-weighting.
            seen = set()
            if strict_preserve_identity:
                for ref in refs_combined[:4]:
                    r = _maybe_data_uri(ref)
                    if r in seen:
                        continue
                    seen.add(r)
                    elements.append(
                        {"reference_image_urls": [r], "frontal_image_url": r}
                    )
                input_data["elements"] = elements
            else:
                # non-strict: single frontal anchor strategy
                # Always prefer an explicit img1 anchor when available.
                if initial_frontal_candidate and initial_frontal_candidate not in seen:
                    elements.append(
                        {
                            "reference_image_urls": [initial_frontal_candidate],
                            "frontal_image_url": initial_frontal_candidate,
                            "face_preservation": 100,
                        }
                    )
                    seen.add(initial_frontal_candidate)
                elif frontal_from_image:
                    elements.append(
                        {
                            "reference_image_urls": [image_url] if image_url else [],
                            "frontal_image_url": frontal_from_image,
                        }
                    )
                    if image_url:
                        seen.add(image_url)
                first_used = False
                for ref in refs_combined[:4]:
                    r = _maybe_data_uri(ref)
                    if r in seen:
                        continue
                    seen.add(r)
                    if (
                        preserve_identity
                        and not frontal_from_image
                        and not first_used
                        and not initial_frontal_candidate
                    ):
                        elements.append(
                            {
                                "reference_image_urls": [r],
                                "frontal_image_url": r,
                                "face_preservation": 100,
                            }
                        )
                        first_used = True
                    else:
                        elements.append({"reference_image_urls": [r]})
                input_data["elements"] = elements
                if preserve_identity and not frontal_from_image and not first_used:
                    elements.append(
                        {"reference_image_urls": [r], "frontal_image_url": r}
                    )
                    first_used = True
                else:
                    elements.append({"reference_image_urls": [r]})

            input_data["elements"] = elements

            # (elements already assigned above)
        if seed:
            input_data["seed"] = seed

        # Best-practice: retry transient errors with exponential backoff,
        # and enforce a reasonable timeout on the blocking call.
        max_retries = 3
        base_delay = 1.0
        # Build a callable that will call predictions.create on whichever client
        # object is available (self.client or the replicate module). This makes it
        # easier to monkeypatch in tests by setting replicate.Client to return a
        # fake client instance.
        # If no webhook_url supplied, prefer the dedicated replicate webhook
        # endpoint configured in settings so Replicate callbacks arrive at
        # /webhook/replicate instead of the generic /webhook/kling. Do this
        # before we build the create callable so the correct value is captured
        # by the closure.
        if not webhook_url and config.WEBHOOK_HOST:
            webhook_url = config.replicate_notification_url

        def _make_create_callable():
            # Return a callable that, when invoked, will perform the
            # synchronous predictions.create call on the appropriate client.
            if self.client:

                def _call():
                    return self.client.predictions.create(
                        model=self.MODEL_VERSION,
                        input=input_data,
                        webhook=webhook_url,
                        webhook_events_filter=["completed"] if webhook_url else None,
                    )

                return _call
            else:

                def _call():
                    return replicate.predictions.create(
                        model=self.MODEL_VERSION,
                        input=input_data,
                        webhook=webhook_url,
                        webhook_events_filter=["completed"] if webhook_url else None,
                    )

                return _call

        # Create the callable with the (possibly updated) webhook_url so it is
        # captured correctly by the function and used when making the request.
        create_callable = _make_create_callable()

        last_exc: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                # Protect the blocking call with asyncio.wait_for to avoid hangs
                prediction = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, create_callable),
                    timeout=60,
                )
                logger.info(f"Runway prediction created: {prediction.id}")
                # If the prediction already finished synchronously (e.g. the
                # model returned a succeeded/failed/canceled status immediately),
                # normalize and return the parsed status including any output
                # URLs. This prevents callers from seeing a transient 'succeeded'
                # without associated output and makes behavior consistent when
                # reference images cause the model to process synchronously.
                if prediction.status in ["succeeded", "failed", "canceled"]:
                    # The prediction finished synchronously. Include the
                    # original prediction id so callers can record the
                    # task and/or correlate webhooks. Keep the parsed
                    # status and generated URLs provided by get_task_status.
                    parsed = await self.get_task_status(prediction.id)
                    if isinstance(parsed, dict):
                        parsed["task_id"] = prediction.id
                    return parsed

                # Normal async case: return task id and current status so
                # callers can store the task and wait for a webhook.
                return {"task_id": prediction.id, "status": prediction.status}

            except asyncio.TimeoutError as te:
                last_exc = te
                logger.warning(
                    f"Runway prediction create timed out (attempt {attempt}/{max_retries})"
                )
            except Exception as e:
                # For replicate exceptions we could inspect type/message to
                # decide whether to retry or not. For now: retry on any
                # exception up to max_retries, treating as transient.
                last_exc = e
                logger.warning(
                    f"Runway API call failed on attempt {attempt}/{max_retries}: {e}"
                )

            # Backoff before next attempt (jittered)
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                # add small jitter
                await asyncio.sleep(delay + (0.1 * attempt))

        # If we get here all attempts failed
        logger.error(f"Runway API error after {max_retries} attempts: {last_exc}")
        return {"error": "api_error", "message": str(last_exc)}

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Получить статус предсказания"""
        try:
            # Build a simple callable that fetches the prediction synchronously
            # in a thread executor. Avoid nested lambdas which are harder to
            # reason about and caused confusion.
            if self.client:

                def _get():
                    return self.client.predictions.get(task_id)

            else:

                def _get():
                    return replicate.predictions.get(task_id)

            prediction = await asyncio.get_event_loop().run_in_executor(None, _get)
            if prediction.status in ["succeeded", "failed", "canceled"]:
                output = getattr(prediction, "output", None)
                # Normalize output to a list of URLs (strings).
                urls: List[str] = []
                if prediction.status == "succeeded" and output:
                    try:
                        outputs = output if isinstance(output, list) else [output]
                        for o in outputs:
                            # FileOutput objects from replicate have .url attribute
                            if hasattr(o, "url"):
                                urls.append(getattr(o, "url"))
                            elif isinstance(o, str):
                                urls.append(o)
                            else:
                                # Last resort: string representation
                                urls.append(str(o))
                    except Exception:
                        logger.exception("Failed to parse prediction.output")

                    # Filter out empty/None entries
                    urls = [u for u in urls if u]
                    if urls:
                        logger.info(
                            f"Runway prediction {task_id} succeeded, urls: {urls}"
                        )
                        return {
                            "status": "COMPLETED",
                            "generated": [{"url": u} for u in urls],
                        }
                    else:
                        logger.warning(
                            f"Runway prediction {task_id} succeeded but no URLs found in output: {output}"
                        )
                        return {"status": "COMPLETED", "generated": []}
                elif prediction.status == "failed":
                    # Try to provide useful error information
                    err = getattr(prediction, "error", None) or getattr(
                        prediction, "logs", None
                    )
                    return {"status": "FAILED", "error": err}
            return {"status": prediction.status}
        except Exception as e:
            logger.error(f"Error getting Runway status {task_id}: {e}")
            return None

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 60, delay: int = 10
    ) -> Optional[Dict]:
        """Ожидание завершения задачи с polling"""
        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if status:
                task_status = status.get("status", "").lower()
                if task_status in ["completed", "succeeded"]:
                    logger.info(f"Runway task {task_id} completed")
                    return status
                elif task_status in ["failed", "error", "canceled"]:
                    logger.error(f"Runway task {task_id} failed")
                    return status
            await asyncio.sleep(delay)
        logger.warning(f"Runway task {task_id} timeout")
        return None


runway_service = RunwayService()
