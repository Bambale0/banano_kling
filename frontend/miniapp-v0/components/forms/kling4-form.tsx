"use client";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Kling4ApiError,
  kling4Request,
  uploadKling4,
  type Kling4Element,
  type Kling4Recipe,
  type Kling4Quote,
  type Kling4Task,
  type Kling4Voice,
} from "@/lib/kling4-api";

const UploadBusy = createContext<(delta: number) => void>(() => undefined);

function Media({
  label,
  kind,
  urls,
  onChange,
  max = 1,
}: {
  label: string;
  kind: "image" | "video" | "audio";
  urls: string[];
  onChange: (u: string[]) => void;
  max?: number;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [progress, setProgress] = useState(0),
    [link, setLink] = useState("");
  const notify = useContext(UploadBusy);
  const controller = useRef<AbortController | null>(null);
  const current = useRef(urls);
  current.current = urls;
  useEffect(() => () => controller.current?.abort(), []);
  async function run(file?: File) {
    if (busy) return;
    const ctrl = new AbortController();
    controller.current = ctrl;
    setBusy(true);
    notify(1);
    setError("");
    setProgress(0);
    try {
      const url = file
        ? await uploadKling4(kind, file, ctrl.signal, setProgress)
        : (
            await kling4Request<{ url: string }>(
              "media/import",
              { kind, url: link },
              ctrl.signal,
            )
          ).url;
      if (ctrl.signal.aborted) return;
      onChange([...current.current, url].slice(-max));
      setLink("");
    } catch (e) {
      if (!ctrl.signal.aborted)
        setError(e instanceof Error ? e.message : "Ошибка загрузки.");
    } finally {
      notify(-1);
      if (controller.current === ctrl) {
        controller.current = null;
        setBusy(false);
      }
    }
  }
  return (
    <fieldset
      className="space-y-2 rounded-xl border border-border p-3"
      aria-label={label}
    >
      <legend className="px-1 text-sm">
        {label} · {urls.length}/{max}
      </legend>
      {urls.map((url, i) => (
        <div key={url + String(i)} className="flex items-center gap-2 text-xs">
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="min-w-0 flex-1 truncate"
          >
            {kind === "image" ? (
              <img
                src={url}
                alt={`${label} ${i + 1}`}
                className="h-14 w-20 rounded object-cover"
              />
            ) : (
              `${label} ${i + 1}`
            )}
          </a>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy || !i}
            onClick={() => {
              const next = [...urls];
              [next[i - 1], next[i]] = [next[i], next[i - 1]];
              onChange(next);
            }}
            aria-label={`Переместить ${label} ${i + 1} вверх`}
          >
            ↑
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => onChange(urls.filter((_, n) => n !== i))}
            aria-label={`Удалить ${label} ${i + 1}`}
          >
            ×
          </Button>
        </div>
      ))}
      {urls.length < max && (
        <>
          <Input
            aria-label={`Загрузить ${label}`}
            type="file"
            accept={
              kind === "image"
                ? "image/png,image/jpeg,image/webp"
                : kind === "video"
                  ? "video/mp4"
                  : "audio/mpeg,audio/wav"
            }
            disabled={busy}
            onChange={(event) => {
              const target = event.currentTarget;
              const file = target.files?.[0];
              if (file)
                void run(file).finally(() => {
                  target.value = "";
                });
            }}
          />
          <div className="flex gap-2">
            <Input
              aria-label={`Ссылка ${label}`}
              placeholder="https://…"
              value={link}
              disabled={busy}
              onChange={(e) => setLink(e.target.value)}
            />
            <Button
              type="button"
              variant="outline"
              disabled={busy || !link}
              onClick={() => void run()}
            >
              Импорт
            </Button>
          </div>
        </>
      )}
      {busy && (
        <div className="flex items-center gap-2 text-xs">
          <span role="status">Загрузка {progress}%</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => controller.current?.abort()}
          >
            Отменить
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </fieldset>
  );
}

const fresh = (): Kling4Recipe => ({
  mode: "reference",
  input: { prompt: "", duration: 5, resolution: "720p", aspect_ratio: "auto" },
});
export function Kling4Form({ modelSelector }: { modelSelector: ReactNode }) {
  const [recipe, setRecipe] = useState<Kling4Recipe>(fresh),
    [quote, setQuote] = useState<Kling4Quote | null>(null),
    [task, setTask] = useState<Kling4Task | null>(null);
  const [history, setHistory] = useState<Kling4Task[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState(""),
    [revision, setRevision] = useState(0);
  const [uploadCount, setUploadCount] = useState(0);
  const drafts = useRef<Partial<Record<Kling4Recipe["mode"], Kling4Recipe>>>(
    {},
  );
  const key = useRef(crypto.randomUUID()),
    input = recipe.input;
  const [uncertain, setUncertain] = useState(false);
  const locked =
    uncertain || Boolean(task && !["done", "failed"].includes(task.status));
  function change(next: Kling4Recipe) {
    if (locked) return;
    setRecipe(next);
    setQuote(null);
    setTask(null);
    key.current = crypto.randomUUID();
  }
  function patch(next: Partial<Kling4Recipe["input"]>) {
    change({ ...recipe, input: { ...input, ...next } });
  }
  function element(index: number, next: Partial<Kling4Element>) {
    patch({
      elements: (input.elements || []).map((e, i) =>
        i === index ? { ...e, ...next } : e,
      ),
    });
  }
  function voice(index: number, next: Partial<Kling4Voice>) {
    patch({
      voices: (input.voices || []).map((e, i) =>
        i === index ? { ...e, ...next } : e,
      ),
    });
  }
  async function refresh() {
    const data = await kling4Request<{ tasks: Kling4Task[] }>("history");
    setHistory(data.tasks);
  }
  useEffect(() => {
    void refresh().catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!task || ["done", "failed"].includes(task.status)) return;
    const timer = setInterval(() => {
      void kling4Request<Kling4Task>("status", { task_id: task.task_id })
        .then(setTask)
        .catch(() => undefined);
    }, 10000);
    return () => clearInterval(timer);
  }, [task?.task_id, task?.status]);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка Kling 4.");
    } finally {
      setBusy(false);
    }
  }
  async function launch() {
    if (!quote) return;
    setUncertain(true);
    try {
      const result = await kling4Request<Kling4Task>("generate", {
        recipe,
        quote_hash: quote.quote_hash,
        idempotency_key: key.current,
      });
      setTask(result);
      setUncertain(false);
      await refresh();
    } catch (error) {
      if (
        error instanceof Kling4ApiError &&
        error.status >= 400 &&
        error.status < 500
      )
        setUncertain(false);
      throw error;
    }
  }
  const tags =
    recipe.mode === "reference"
      ? [
          ...(input.image_urls || []).map((_, i) => `image_${i + 1}`),
          ...(input.video_urls || []).map((_, i) => `video_${i + 1}`),
          ...(input.elements || []).map((e) => e.name),
          ...(input.voices || []).map((v) => v.name),
        ]
      : [
          ...(input.first_frame_url ? ["first_frame"] : []),
          ...(input.keyframe_urls || []).map((_, i) => `keyframe_${i + 1}`),
          ...(input.last_frame_url ? ["last_frame"] : []),
        ];
  return (
    <UploadBusy.Provider
      value={(delta) => setUploadCount((count) => Math.max(0, count + delta))}
    >
      <div className="space-y-4" data-testid="kling4-form">
        <div className="glass space-y-4 rounded-2xl border border-cyan/20 p-4">
          {modelSelector}
          <p className="text-xs text-muted-foreground">
            Kling 4 · доступ администратора · бананы не списываются
          </p>
          <fieldset disabled={busy || locked} className="space-y-4">
            <label className="block text-sm">
              Режим
              <select
                aria-label="Режим Kling 4"
                className="mt-1 block w-full rounded border bg-background p-2"
                value={recipe.mode}
                onChange={(e) => {
                  drafts.current[recipe.mode] = recipe;
                  const mode = e.target.value as Kling4Recipe["mode"];
                  change(
                    drafts.current[mode] || {
                      mode,
                      input: {
                        prompt: input.prompt,
                        duration: input.duration,
                        resolution: input.resolution,
                        aspect_ratio: input.aspect_ratio,
                      },
                    },
                  );
                }}
              >
                <option value="reference">
                  Reference · референсы и персонажи
                </option>
                <option value="keyframe">
                  Keyframe · последовательность кадров
                </option>
              </select>
            </label>
            <label className="block text-sm">
              Промпт
              <Textarea
                aria-label="Промпт Kling 4"
                value={input.prompt}
                maxLength={8000}
                onChange={(e) => patch({ prompt: e.target.value })}
                placeholder="Опишите движение, сцену и звук…"
              />
            </label>
            {!!tags.length && (
              <div
                className="flex flex-wrap gap-1"
                aria-label="Теги материалов"
              >
                {tags.filter(Boolean).map((tag) => (
                  <Button
                    key={tag}
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => patch({ prompt: input.prompt + ` @${tag}` })}
                  >
                    @{tag}
                  </Button>
                ))}
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <label className="text-sm">
                Длительность, с
                <Input
                  aria-label="Длительность Kling 4"
                  type="number"
                  min={3}
                  max={30}
                  step={1}
                  value={input.duration}
                  onChange={(e) => patch({ duration: Number(e.target.value) })}
                />
              </label>
              <label className="text-sm">
                Разрешение
                <select
                  aria-label="Разрешение Kling 4"
                  className="block w-full rounded border bg-background p-2"
                  value={input.resolution}
                  onChange={(e) => patch({ resolution: e.target.value })}
                >
                  <option>720p</option>
                  <option>1080p</option>
                </select>
              </label>
            </div>
            <label className="block text-sm">
              Пропорции
              <select
                aria-label="Пропорции Kling 4"
                className="block w-full rounded border bg-background p-2"
                value={input.aspect_ratio || "auto"}
                onChange={(e) => patch({ aspect_ratio: e.target.value })}
              >
                {["auto", "16:9", "9:16", "1:1", "21:9"].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </label>
            {recipe.mode === "keyframe" ? (
              <>
                <p className="text-xs text-muted-foreground">
                  До {Math.min(10, input.duration + 1)} кадров всего. Порядок
                  промежуточных кадров можно менять. Пропорции берутся из
                  ведущего кадра.
                </p>
                <Media
                  label="Первый кадр"
                  kind="image"
                  urls={input.first_frame_url ? [input.first_frame_url] : []}
                  onChange={(u) => patch({ first_frame_url: u[0] })}
                />
                <Media
                  label="Промежуточные кадры"
                  kind="image"
                  max={8}
                  urls={input.keyframe_urls || []}
                  onChange={(u) => patch({ keyframe_urls: u })}
                />
                <Media
                  label="Последний кадр"
                  kind="image"
                  urls={input.last_frame_url ? [input.last_frame_url] : []}
                  onChange={(u) => patch({ last_frame_url: u[0] })}
                />
              </>
            ) : (
              <>
                <Media
                  label="Референсы фото"
                  kind="image"
                  max={10}
                  urls={input.image_urls || []}
                  onChange={(u) => patch({ image_urls: u })}
                />
                <Media
                  label="Референсы видео"
                  kind="video"
                  max={5}
                  urls={input.video_urls || []}
                  onChange={(u) =>
                    patch({
                      video_urls: u,
                      ...(!u.length ? { keep_original_sound: undefined } : {}),
                    })
                  }
                />
                {!!input.video_urls?.length && (
                  <label className="flex gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={input.keep_original_sound || false}
                      onChange={(e) =>
                        patch({ keep_original_sound: e.target.checked })
                      }
                    />
                    Сохранить исходный звук видео
                  </label>
                )}
                <div className="space-y-3">
                  <p className="text-sm">Персонажи и объекты · до 7</p>
                  {(input.elements || []).map((item, i) => (
                    <div
                      key={i}
                      className="space-y-2 rounded-xl border border-border p-3"
                    >
                      <Input
                        aria-label={`Имя элемента ${i + 1}`}
                        placeholder="Hero (латиница, цифры, _)"
                        value={item.name}
                        onChange={(e) => element(i, { name: e.target.value })}
                      />
                      <select
                        aria-label={`Тип элемента ${i + 1}`}
                        className="w-full rounded border bg-background p-2 text-sm"
                        value={item.tag || "character"}
                        onChange={(e) => element(i, { tag: e.target.value })}
                      >
                        {[
                          "character",
                          "animal",
                          "prop",
                          "costume",
                          "scene",
                          "effect",
                          "others",
                        ].map((t) => (
                          <option key={t} value={t}>
                            {
                              (
                                {
                                  character: "Персонаж",
                                  animal: "Животное",
                                  prop: "Предмет",
                                  costume: "Одежда",
                                  scene: "Сцена",
                                  effect: "Эффект",
                                  others: "Другое",
                                } as Record<string, string>
                              )[t]
                            }
                          </option>
                        ))}
                      </select>
                      <Input
                        aria-label={`Описание элемента ${i + 1}`}
                        maxLength={100}
                        placeholder="Описание до 100 символов"
                        value={item.description || ""}
                        onChange={(e) =>
                          element(i, { description: e.target.value })
                        }
                      />
                      {"video_url" in item ? (
                        <Media
                          label={`Видео персонажа ${i + 1}`}
                          kind="video"
                          urls={item.video_url ? [item.video_url] : []}
                          onChange={(u) =>
                            element(i, { video_url: u[0] || "" })
                          }
                        />
                      ) : (
                        <Media
                          label={`Фото элемента ${i + 1} (2–4)`}
                          kind="image"
                          max={4}
                          urls={item.image_urls || []}
                          onChange={(u) => element(i, { image_urls: u })}
                        />
                      )}
                      {(!item.tag || item.tag === "character") && (
                        <Media
                          label={`Голос персонажа ${i + 1}`}
                          kind="audio"
                          urls={item.voice_url ? [item.voice_url] : []}
                          onChange={(u) => element(i, { voice_url: u[0] })}
                        />
                      )}
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          patch({
                            elements: input.elements?.filter((_, n) => n !== i),
                          })
                        }
                      >
                        Удалить элемент
                      </Button>
                    </div>
                  ))}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      disabled={(input.elements?.length || 0) >= 7}
                      onClick={() =>
                        patch({
                          elements: [
                            ...(input.elements || []),
                            { name: "", tag: "character", image_urls: [] },
                          ],
                        })
                      }
                    >
                      + Элемент по фото
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={(input.elements?.length || 0) >= 7}
                      onClick={() =>
                        patch({
                          elements: [
                            ...(input.elements || []),
                            { name: "", tag: "character", video_url: "" },
                          ],
                        })
                      }
                    >
                      + Персонаж по видео
                    </Button>
                  </div>
                </div>
                <div className="space-y-3">
                  <p className="text-sm">Отдельные голоса · до 3</p>
                  {(input.voices || []).map((item, i) => (
                    <div
                      key={i}
                      className="space-y-2 rounded-xl border border-border p-3"
                    >
                      <Input
                        aria-label={`Имя голоса ${i + 1}`}
                        placeholder="Narrator"
                        value={item.name}
                        onChange={(e) => voice(i, { name: e.target.value })}
                      />
                      <Media
                        label={`Аудио голоса ${i + 1}`}
                        kind="audio"
                        urls={item.audio_url ? [item.audio_url] : []}
                        onChange={(u) => voice(i, { audio_url: u[0] || "" })}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          patch({
                            voices: input.voices?.filter((_, n) => n !== i),
                          })
                        }
                      >
                        Удалить голос
                      </Button>
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    disabled={(input.voices?.length || 0) >= 3}
                    onClick={() =>
                      patch({
                        voices: [
                          ...(input.voices || []),
                          { name: "", audio_url: "" },
                        ],
                      })
                    }
                  >
                    + Голос
                  </Button>
                </div>
              </>
            )}
          </fieldset>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {quote && (
            <div className="rounded-xl bg-secondary p-3 text-sm" role="status">
              {"\u0420\u0430\u0441\u0445\u043e\u0434 KIE: "}{quote.provider_credits} credits ·{" "}
              {quote.billed_seconds}{" "}
              {"\u043e\u043f\u043b\u0430\u0447\u0438\u0432\u0430\u0435\u043c\u044b\u0445 \u0441\u0435\u043a\u0443\u043d\u0434. \u0426\u0435\u043d\u0430: "}{quote.cost}{" "}
              {"\u0431\u0430\u043d\u0430\u043d\u043e\u0432. \u0414\u043b\u044f \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430 \u0441\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u043e\u0442\u043a\u043b\u044e\u0447\u0435\u043d\u043e."}
            </div>
          )}
          {!locked && (
            <Button
              type="button"
              disabled={busy || uploadCount > 0 || !input.prompt.trim()}
              onClick={() =>
                void action(async () => {
                  setQuote(
                    await kling4Request<Kling4Quote>("quote", { recipe }),
                  );
                })
              }
            >
              Рассчитать Kling 4
            </Button>
          )}
          {quote && !task && !uncertain && (
            <Button
              type="button"
              disabled={busy || uploadCount > 0}
              onClick={() => void action(launch)}
            >
              Подтвердить и создать
            </Button>
          )}
          {uncertain && !task && (
            <div role="status" className="space-y-2 text-sm">
              <p>
                Подтверждение запуска не получено. Настройки сохранены; новый
                ключ не создаётся.
              </p>
              <Button
                type="button"
                disabled={busy}
                onClick={() => void action(launch)}
              >
                Повторить отправку с тем же ключом
              </Button>
            </div>
          )}
          {task && (
            <div className="space-y-2 text-sm" role="status">
              <p>Задача: {task.task_id}</p>
              <p>
                {task.status === "unknown"
                  ? "Ответ KIE не подтверждён. Повторная генерация заблокирована; проверьте кабинет KIE и привяжите ID задачи."
                  : `Статус: ${task.status}`}
              </p>
              {task.actual_credits !== null && (
                <p>Фактический расход: {task.actual_credits} KIE credits</p>
              )}
              {task.result_url && (
                <>
                  <video
                    controls
                    playsInline
                    src={task.result_url}
                    className="w-full rounded-xl"
                  />
                  <a
                    className="underline"
                    href={task.result_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Скачать оригинал
                  </a>
                </>
              )}
              {["done", "failed"].includes(task.status) && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setTask(null);
                    setQuote(null);
                    key.current = crypto.randomUUID();
                    void refresh();
                  }}
                >
                  Новая генерация с этими настройками
                </Button>
              )}
            </div>
          )}
        </div>
        <details className="glass rounded-2xl p-4">
          <summary>История Kling 4</summary>
          <Button
            type="button"
            variant="outline"
            onClick={() => void action(refresh)}
          >
            Обновить историю
          </Button>
          {history.map((item) => (
            <div
              key={item.task_id}
              className="space-y-2 border-b border-border py-3 text-xs"
            >
              <p className="break-all">
                {item.task_id} · {item.status} · KIE{" "}
                {item.actual_credits ?? "уточняется"}
              </p>
              {item.result_url && (
                <a
                  href={item.result_url}
                  target="_blank"
                  rel="noreferrer"
                  className="underline"
                >
                  Скачать оригинал
                </a>
              )}
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy || locked}
                onClick={() =>
                  void action(async () => {
                    const data = await kling4Request<{ recipe: Kling4Recipe }>(
                      "recipe",
                      { task_id: item.task_id },
                    );
                    change(data.recipe);
                  })
                }
              >
                Повторить в редакторе
              </Button>
              {item.status === "unknown" && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const id = String(
                      new FormData(e.currentTarget).get("provider_task_id") ||
                        "",
                    );
                    void action(async () => {
                      await kling4Request("adopt", {
                        task_id: item.task_id,
                        provider_task_id: id,
                      });
                      await refresh();
                    });
                  }}
                >
                  <Input
                    aria-label={`ID KIE для ${item.task_id}`}
                    name="provider_task_id"
                    placeholder="ID из кабинета KIE"
                    required
                  />
                  <Button type="submit" size="sm">
                    Привязать подтверждённую задачу
                  </Button>
                </form>
              )}
            </div>
          ))}
        </details>
        <details className="glass rounded-2xl p-4">
          <summary>Настройки Kling 4 · администратор</summary>
          <p className="my-2 text-xs">
            Версионируемые тарифы и ограничения. Публичный доступ закрыт.
          </p>
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              void action(async () => {
                const data = await kling4Request<{
                  settings: unknown;
                  revision: number;
                }>("settings");
                setSettings(JSON.stringify(data.settings, null, 2));
                setRevision(data.revision);
              })
            }
          >
            Загрузить настройки
          </Button>
          {settings && (
            <>
              <Textarea
                aria-label="Настройки Kling 4"
                className="my-2 min-h-64 font-mono text-xs"
                value={settings}
                onChange={(e) => setSettings(e.target.value)}
              />
              <Button
                type="button"
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    const data = await kling4Request<{ revision: number }>(
                      "settings",
                      { settings: JSON.parse(settings), revision },
                    );
                    setRevision(data.revision);
                  })
                }
              >
                Сохранить ревизию {revision + 1}
              </Button>
            </>
          )}
        </details>
      </div>
    </UploadBusy.Provider>
  );
}
