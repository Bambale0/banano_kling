'use client'

import { useEffect, useRef, useState, type RefObject } from 'react'
import { getInitData } from '../../lib/api'

export type AstroReportService = 'natal' | 'compatibility' | 'karma' | 'year' | 'month' | 'solar' | 'lunar'

type BirthInput = { date: string; time: string; place_id: number; fold?: number }

interface HistoryItem {
  job_id: string
  service_id: AstroReportService
  status: string
  attempts: number
  created_at: number
  error_code?: string | null
}

interface LongReport {
  schema_version: 'astro.report.v1'
  service_id: AstroReportService
  word_count: number
  sections: Array<{ id: string; title: string; text: string }>
  disclaimer: string
}

function cityId(value: FormDataEntryValue | null, label: string): number {
  const raw = String(value ?? '')
  if (!/^[1-9][0-9]{0,9}$/.test(raw)) {
    throw new Error('Выберите город ' + label + ' из предложенного списка.')
  }
  const id = Number(raw)
  if (!Number.isSafeInteger(id) || id > 2147483647) {
    throw new Error('Выберите город ' + label + ' из предложенного списка.')
  }
  return id
}

function validBirthDate(raw: string): boolean {
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(raw)
  if (!match) return false
  const day = Number(match[1]); const month = Number(match[2]); const year = Number(match[3])
  if (year < 1900 || year > 2100 || month < 1 || month > 12 || day < 1 || day > 31) return false
  const utc = new Date(Date.UTC(year, month - 1, day))
  return utc.getUTCFullYear() === year && utc.getUTCMonth() === month - 1 && utc.getUTCDate() === day
}

function birthFromForm(form: FormData, prefix: 'person' | 'partner'): BirthInput {
  const date = String(form.get(prefix + '-date') ?? '').trim()
  if (!validBirthDate(date)) throw new Error('Укажите корректную дату рождения (ДД.ММ.ГГГГ).')
  const time = String(form.get(prefix + '-time') ?? '')
  if (time && !/^([01][0-9]|2[0-3]):[0-5][0-9]$/.test(time)) {
    throw new Error('Укажите корректное время рождения.')
  }
  const place_id = cityId(form.get(prefix + '-place-id'), 'рождения')
  const fold = String(form.get(prefix + '-fold') ?? form.get('birth-fold') ?? '')
  return { date, time, place_id, ...(fold === '0' || fold === '1' ? { fold: Number(fold) } : {}) }
}

export function buildAstroReportInput(
  service: AstroReportService, form: FormData, period: string,
): Record<string, unknown> {
  if (service === 'lunar') {
    if (!/^(19|20)\d{2}-(0[1-9]|1[0-2])$|^2100-(0[1-9]|1[0-2])$/.test(period)) {
      throw new Error('Выберите месяц для лунного календаря.')
    }
    return { period, place_id: cityId(form.get('lunar-place-id'), 'календаря') }
  }
  if (service === 'compatibility') {
    return { person_a: birthFromForm(form, 'person'), person_b: birthFromForm(form, 'partner') }
  }
  const profile = birthFromForm(form, 'person')
  if (service === 'natal' || service === 'karma') return profile
  if (service === 'month') {
    if (!/^(19|20)\d{2}-(0[1-9]|1[0-2])$|^2100-(0[1-9]|1[0-2])$/.test(period)) {
      throw new Error('Выберите корректный месяц прогноза.')
    }
    return { ...profile, period }
  }
  if (!/^(19|20)\d{2}$|^2100$/.test(period)) {
    throw new Error('Выберите год прогноза от 1900 до 2100.')
  }
  if (service === 'solar') {
    if (!profile.time) throw new Error('Для соляра укажите точное время рождения.')
    return { ...profile, period, return_place_id: cityId(form.get('solar-place-id'), 'соляра') }
  }
  return { ...profile, period }
}

const REPORTS_ROOT = '/mini-app/api/astro/reports'
const REFRESH_MS = 6000

export function AstroReportPanel({ service, formRef, period, formRevision = 0 }: {
  service: AstroReportService
  formRef: RefObject<HTMLFormElement | null>
  period: string
  formRevision?: number
}) {
  const [consent, setConsent] = useState(false)
  const [availability, setAvailability] = useState<'ready' | 'disabled'>('ready')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [jobId, setJobId] = useState('')
  const [jobStatus, setJobStatus] = useState('')
  const [pollEpoch, setPollEpoch] = useState(0)
  const [report, setReport] = useState<LongReport | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const historyAbort = useRef<AbortController | null>(null)
  const requestEpoch = useRef(0)
  const lastFormRevision = useRef(formRevision)

  useEffect(() => {
    if (lastFormRevision.current === formRevision) return
    lastFormRevision.current = formRevision
    requestEpoch.current += 1
    setConsent(false)
    setReport(null)
    setJobId('')
    setJobStatus('')
    setMessage('Исходные данные изменены. Предыдущий разбор можно открыть через историю.')
  }, [formRevision])

  useEffect(() => {
    requestEpoch.current += 1
    historyAbort.current?.abort()
    setHistory([])
    setReport(null)
    setJobId('')
    setJobStatus('')
    setMessage('')
    setAvailability('ready')
    setHistoryLoading(false)
    return () => { requestEpoch.current += 1; historyAbort.current?.abort() }
  }, [service])

  async function loadHistory() {
    const epoch = requestEpoch.current
    historyAbort.current?.abort()
    const controller = new AbortController()
    historyAbort.current = controller
    setHistoryLoading(true)
    try {
      const response = await fetch(REPORTS_ROOT + '/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: getInitData(), service_id: service }),
        signal: controller.signal,
      })
      if (controller.signal.aborted || epoch !== requestEpoch.current) return
      if (response.status === 503 || response.status === 401 || response.status === 403) {
        // Only an auth/role rejection blocks access; a 503 is recoverable.
        setAvailability(response.status === 503 ? 'ready' : 'disabled')
        setMessage(response.status === 503
          ? 'Отчёты временно недоступны. Попробуйте ещё раз чуть позже.'
          : 'Откройте раздел в Telegram с правами администратора.')
        return
      }
      const data = await response.json()
      if (controller.signal.aborted || epoch !== requestEpoch.current) return
      if (!response.ok || !data.ok || !Array.isArray(data.jobs)) {
        setMessage('Не удалось получить историю отчётов. Повторите позднее.')
        return
      }
      setHistory((data.jobs as HistoryItem[]).filter((item) =>
        item.service_id === service && /^[0-9a-f]{32}$/.test(item.job_id)
      ))
      setAvailability('ready')
      setMessage(data.jobs.length ? 'История загружена.' : 'Ранее созданных отчётов пока нет.')
    } catch {
      if (!controller.signal.aborted && epoch === requestEpoch.current) {
        setMessage('История отчётов временно недоступна.')
      }
    } finally {
      if (!controller.signal.aborted && epoch === requestEpoch.current) setHistoryLoading(false)
    }
  }

  useEffect(() => {
    if (!jobId) return
    let alive = true
    let nextPoll: ReturnType<typeof setTimeout> | undefined
    const controller = new AbortController()
    async function poll() {
      let finished = false
      try {
        const response = await fetch(REPORTS_ROOT + '/status', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ init_data: getInitData(), job_id: jobId }),
          signal: controller.signal,
        })
        if (!alive) return
        if (response.status === 401 || response.status === 403) {
          setMessage('Доступ к отчёту отозван. Откройте приложение заново.')
          setReport(null)
          finished = true
        } else if (response.status === 503) {
          setMessage('Подготовка временно приостановлена. Ваш разбор сохранён.')
        } else if (response.status === 404) {
          setMessage('Отчёт не найден или срок его хранения истёк.')
          setReport(null)
          finished = true
        } else {
          const data = await response.json()
          if (!alive) return
          if (!response.ok || !data.ok) {
            setMessage('Не удалось получить статус отчёта. Повторим запрос.')
          } else {
            setJobStatus(data.status)
            if (data.status === 'completed' && data.report?.schema_version === 'astro.report.v1'
              && data.report.service_id === service && Array.isArray(data.report.sections)) {
              setReport(data.report as LongReport)
              setMessage('Полный разбор готов и сохранён в истории.')
              finished = true
            } else if (data.status === 'failed') {
              setReport(null)
              setMessage('Не удалось завершить разбор. Баланс не списан.')
              finished = true
            }
          }
        }
      } catch {
        if (alive && !controller.signal.aborted) setMessage('Связь прервалась. Повторяем проверку статуса.')
      }
      if (alive && !finished) nextPoll = setTimeout(() => { void poll() }, REFRESH_MS)
    }
    void poll()
    return () => {
      alive = false
      controller.abort()
      if (nextPoll) clearTimeout(nextPoll)
    }
  }, [jobId, service, pollEpoch])

  async function startReport() {
    if (busy || availability !== 'ready') return
    if (!consent) {
      setMessage('Подтвердите согласие на обработку данных для персонального ИИ-разбора.')
      return
    }
    const formElement = formRef.current
    if (!formElement) {
      setMessage('Форма недоступна. Повторно откройте раздел Astro.')
      return
    }
    let input: Record<string, unknown>
    try {
      input = buildAstroReportInput(service, new FormData(formElement), period)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Проверьте данные расчёта.')
      return
    }
    const epoch = requestEpoch.current
    setBusy(true)
    setMessage('Проверяем данные и начинаем разбор…')
    try {
      const response = await fetch(REPORTS_ROOT + '/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: getInitData(), service_id: service, consent: true, input }),
      })
      if (epoch !== requestEpoch.current) return
      if (response.status === 401 || response.status === 403) {
        setMessage('Для создания отчёта откройте приложение Telegram с правами администратора.')
        return
      }
      if (response.status === 503) {
        // A disabled backend may be enabled while this Mini App remains mounted.
        // Keep the explicit-submit path available for a later intentional retry.
        setAvailability('ready')
        setMessage('Сейчас не удаётся создать разбор. Попробуйте чуть позже. Баланс не списан.')
        return
      }
      const data = await response.json()
      if (epoch !== requestEpoch.current) return
      if (response.status !== 202 || !data.ok || typeof data.job_id !== 'string'
        || !/^[0-9a-f]{32}$/.test(data.job_id)) {
        setMessage(data.error === 'storage_consent_required'
          ? 'Необходимо согласие на хранение данных.'
          : 'Не удалось начать разбор. Баланс не списан.')
        return
      }
      setJobId(data.job_id)
      setJobStatus('queued')
      setReport(null)
      setConsent(false)
      setHistory((previous) => previous.some((item) => item.job_id === data.job_id)
        ? previous : [{ job_id: data.job_id, service_id: service, status: 'queued',
                        attempts: 0, created_at: Math.floor(Date.now() / 1000) }, ...previous])
      setPollEpoch((value) => value + 1)
      setMessage('Ваш разбор готовится. Можно закрыть приложение и вернуться к нему через историю.')
    } catch {
      if (epoch === requestEpoch.current) {
        setMessage('Связь прервалась. Попробуйте ещё раз или проверьте историю отчётов.')
      }
    } finally {
      if (epoch === requestEpoch.current) setBusy(false)
    }
  }

  async function retryReport() {
    if (busy || !jobId || jobStatus !== 'failed' || !consent || availability !== 'ready') return
    const epoch = requestEpoch.current
    setBusy(true)
    setMessage('Проверяем возможность продолжить разбор…')
    try {
      const response = await fetch(REPORTS_ROOT + '/retry', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: getInitData(), job_id: jobId, consent: true }),
      })
      if (epoch !== requestEpoch.current) return
      if (response.status === 401 || response.status === 403) {
        setMessage('Повторить отчёт можно только из Telegram с правами администратора.')
        return
      }
      if (response.status === 503) {
        // Keep explicit manual retry available when the queue comes back.
        setAvailability('ready')
        setMessage('Подготовка отчётов временно недоступна. Ваши данные сохранены.')
        return
      }
      if (response.status === 409) {
        setMessage('Сейчас нельзя повторить разбор. Попробуйте позже или обратитесь в поддержку.')
        return
      }
      const data = await response.json()
      if (epoch !== requestEpoch.current) return
      if (response.status !== 202 || !data.ok || data.job_id !== jobId) {
        setMessage('Не удалось безопасно возобновить отчёт.')
        return
      }
      setJobStatus('queued')
      setReport(null)
      setConsent(false)
      setHistory((previous) => previous.map((item) =>
        item.job_id === jobId ? { ...item, status: 'queued', attempts: 0 } : item))
      setPollEpoch((value) => value + 1)
      setMessage('Продолжаем разбор. Готовые разделы сохранены.')
    } catch {
      if (epoch === requestEpoch.current) {
        setMessage('Не удалось проверить повтор. Откройте историю и сверьте статус.')
      }
    } finally {
      if (epoch === requestEpoch.current) setBusy(false)
    }
  }

  return (
    <section className="astro-ai-panel" aria-label="Полный персональный ИИ-разбор">
      <h2>Подробный персональный разбор</h2>
      <p>Ваш персональный разбор появится здесь и сохранится в истории.</p>
      <button type="button" className="astro-ai-history-action"
        disabled={historyLoading} onClick={() => { void loadHistory() }}>
        {historyLoading ? 'Загружаем историю…' : 'Мои предыдущие отчёты'}
      </button>
      {availability === 'ready' && (
        <>
          <label className="astro-ai-consent">
            <input type="checkbox" checked={consent}
              onChange={(event) => setConsent(event.target.checked)} />
            <span>{service === 'compatibility'
              ? 'Подтверждаю согласие обоих людей на обработку данных рождения для разбора и временное хранение отчёта.'
              : 'Согласен(на) на обработку данных для персонального разбора и временное хранение отчёта.'}</span>
          </label>
          <button type="button" className="astro-ai-action" onClick={() => { void startReport() }}
            disabled={busy || !consent}>
            {busy ? 'Начинаем разбор…' : 'Создать полный ИИ-разбор'}
          </button>
          <p className="astro-ai-privacy">Отчёт хранится временно и доступен только вам. Списаний с баланса нет.</p>
        </>
      )}
      {message && <p className="astro-form-message"
        role={message.startsWith('Исходные данные изменены.') ? undefined : 'status'}>{message}</p>}
      {history.length > 0 && (
        <div className="astro-ai-history">
          <h3>Ранее созданные отчёты</h3>
          <ul>
            {history.map((item) => (
              <li key={item.job_id}>
                <span>{new Date(item.created_at * 1000).toLocaleString('ru-RU')}</span>
                <span> · {item.status === 'completed' ? 'готов' : item.status === 'failed'
                  ? 'ошибка' : item.status === 'running' ? 'готовится' : 'ожидает начала'}</span>
                <button type="button" onClick={() => {
                  setReport(null)
                  setJobId(item.job_id)
                  setJobStatus(item.status)
                  setPollEpoch((value) => value + 1)
                }}>Открыть</button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {jobId && jobStatus === 'failed' && availability === 'ready' && (
        <button type="button" className="astro-ai-action"
          disabled={busy || !consent} onClick={() => { void retryReport() }}>
          {busy ? 'Возобновляем отчёт…' : 'Повторить отчёт'}
        </button>
      )}
      {jobId && !report && (jobStatus === 'queued' || jobStatus === 'running') && (
        <div className="astro-ai-progress" role="status" data-testid="astro-live-processing"
          aria-label="Астрологический разбор выполняется">
          <span className="astro-ai-progress-spinner" aria-hidden="true" />
          <div>
            <strong>{jobStatus === 'running' ? 'Готовим ваш персональный разбор…'
              : 'Скоро начнём готовить ваш разбор…'}</strong>
            <span>Можно закрыть приложение. Готовый разбор появится здесь и придёт в Telegram.</span>
          </div>
        </div>
      )}
      {report && (
        <article className="astro-ai-report" aria-label="Готовый полный ИИ-разбор">
          <h2>Ваш персональный разбор</h2>
          {report.sections.map((section) => (
            <section key={section.id} className="astro-ai-report-section">
              <h3>{section.title}</h3>
              <div className="astro-ai-section-text">{section.text}</div>
            </section>
          ))}
          <p className="astro-ai-disclaimer">{report.disclaimer}</p>
        </article>
      )}
    </section>
  )
}
