import { getApiBasePath, getInitData } from "./api";

export type Kling4Mode = "reference" | "keyframe";
export interface Kling4Element {
  name: string;
  image_urls?: string[];
  video_url?: string;
  tag?: string;
  description?: string;
  voice_url?: string;
}
export interface Kling4Voice {
  name: string;
  audio_url: string;
}
export interface Kling4Recipe {
  mode: Kling4Mode;
  input: {
    prompt: string;
    duration: number;
    resolution: string;
    aspect_ratio?: string;
    image_urls?: string[];
    video_urls?: string[];
    keep_original_sound?: boolean;
    elements?: Kling4Element[];
    voices?: Kling4Voice[];
    first_frame_url?: string;
    last_frame_url?: string;
    keyframe_urls?: string[];
  };
}
export interface Kling4Quote {
  quote_hash: string;
  provider_credits: string;
  rate: string;
  billed_seconds: string;
  input_video_seconds: string;
  cost: number;
}
export interface Kling4Task {
  task_id: string;
  status: string;
  provider_task_id: string | null;
  result_url: string | null;
  actual_credits: string | null;
  error_code: string | null;
  delivery_status: string | null;
  quote: Kling4Quote;
}

export class Kling4ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function kling4Request<T>(
  action: string,
  payload: object = {},
  signal?: AbortSignal,
): Promise<T> {
  const initData = getInitData();
  const response = await fetch(`${getApiBasePath()}/kling4/${action}`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": initData,
    },
    body: JSON.stringify({ ...payload, init_data: initData }),
    signal: signal || AbortSignal.timeout(90000),
  });
  const data = await response.json();
  if (!response.ok || data.ok === false)
    throw new Kling4ApiError(
      data.error || "Не удалось выполнить запрос Kling 4.",
      response.status,
    );
  return data as T;
}

/** Original bytes; no implicit image compression/crop/audio conversion. */
export async function uploadKling4(
  kind: "image" | "video" | "audio",
  file: File,
  signal: AbortSignal,
  onProgress: (n: number) => void,
): Promise<string> {
  const maximum = {
    image: 20 * 1024 ** 2,
    video: 200 * 1024 ** 2,
    audio: 30 * 1024 ** 2,
  }[kind];
  if (!file.size || file.size > maximum)
    throw new Error(`Файл: от 1 байта до ${maximum / 1024 ** 2} МБ.`);
  if (kind === "image")
    file = new File([await file.arrayBuffer()], file.name, {
      type: file.type,
      lastModified: file.lastModified,
    });
  const uploadId = crypto.randomUUID().replaceAll("-", "");
  let completed = false;
  try {
    await kling4Request(
      "media/init",
      {
        kind,
        filename: file.name,
        size: file.size,
        content_type: file.type,
        upload_id: uploadId,
      },
      signal,
    );
    const chunkSize = 7 * 1024 ** 2,
      total = Math.ceil(file.size / chunkSize);
    for (let index = 0; index < total; index++) {
      const body = new FormData();
      body.set("upload_id", uploadId);
      body.set("index", String(index));
      body.set("total", String(total));
      body.set("init_data", getInitData());
      body.set(
        "chunk",
        file.slice(index * chunkSize, (index + 1) * chunkSize),
        file.name,
      );
      const response = await fetch(`${getApiBasePath()}/kling4/media/chunk`, {
        method: "POST",
        credentials: "include",
        headers: { "X-Telegram-Init-Data": getInitData() },
        body,
        signal,
      });
      const result = await response.json();
      if (!response.ok || result.ok === false)
        throw new Error(result.error || "Загрузка прервана.");
      onProgress(Math.round(((index + 1) / total) * 100));
    }
    const result = await kling4Request<{ url: string }>(
      "media/complete",
      { upload_id: uploadId },
      signal,
    );
    completed = true;
    return result.url;
  } finally {
    if (!completed)
      await kling4Request("media/cancel", { upload_id: uploadId }).catch(
        () => undefined,
      );
  }
}
