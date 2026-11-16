'use client'

import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ArrowLeft, CalendarDays, ChevronDown, ChevronRight, Clock3,
  MapPin, Search, Sparkles, Star,
} from 'lucide-react'
import { getInitData } from '../../lib/api'
import './astro-tab.css'

type AstroKind = 'natal' | 'compatibility' | 'karma' | 'year' | 'month' | 'solar' | 'lunar'

interface AstroPlace {
  place_id: number
  name: string
  country_code: string
  timezone: string
  latitude: number
  longitude: number
  display_name: string
  source: string
}

interface CompatibilityReport {
  schema_version: string
  person_a: NatalReport
  person_b: NatalReport
  cross_aspects: Array<{
    person_a_body: string
    person_b_body: string
    kind: string
    orb_deg: number
    approximate: boolean
  }>
  warnings: string[]
}

const PLANET_RU: Record<string, string> = {
  Sun: 'Солнце', Moon: 'Луна', Mercury: 'Меркурий', Venus: 'Венера', Mars: 'Марс',
  Jupiter: 'Юпитер', Saturn: 'Сатурн', Uranus: 'Уран', Neptune: 'Нептун', Pluto: 'Плутон',
}
const ASPECT_RU: Record<string, string> = {
  conjunction: 'соединение', sextile: 'секстиль', square: 'квадрат',
  trine: 'трин', opposition: 'оппозиция',
}

interface NatalReport {
  schema_version: string
  timezone: string
  birth_time_known: boolean
  utc_reference: string
  positions: Record<string, {
    sign: string
    degree_in_sign: number
    retrograde: boolean
    approximate: boolean
  }>
  aspects: Array<{ a: string; b: string; kind: string; orb_deg: number }>
  warnings: string[]
}

interface LunarReport {
  period: string
  timezone: string
  days: Array<{
    date: string
    moon_sign: string
    phase: string
    illumination_percent: number
    synodic_day: number
    events: string[]
  }>
  events: Array<{ kind: string; at_local: string }>
  ingresses?: Array<{ from_sign: string; to_sign: string; at_local: string }>
}

interface AstroService {
  id: AstroKind
  title: string
  subtitle?: string
  description: string
}

export const ASTRO_SERVICES: readonly AstroService[] = [
  { id: 'natal', title: 'Натальная карта', description: 'Фактические положения планет и аспекты. Развёрнутый разбор готовится' },
  { id: 'compatibility', title: 'Совместимость', description: 'Реальные межкартные аспекты двух людей. Развёрнутый разбор отношений готовится' },
  { id: 'karma', title: 'Кармический разбор', description: 'Лунные узлы, жизненные темы и символические уроки' },
  { id: 'year', title: 'Годовой прогноз', description: 'Астрологические транзиты и тенденции на выбранный год' },
  { id: 'month', title: 'Гороскоп на месяц', description: 'Персональные астрологические тенденции месяца' },
  { id: 'solar', title: 'Соляр', subtitle: 'Личный год от дня рождения', description: 'Карта солнечного возвращения на новый личный год' },
  { id: 'lunar', title: 'Лунный календарь', description: 'Фазы Луны и ключевые лунные события месяца' },
]

const zodiac = ['♈︎', '♉︎', '♊︎', '♋︎', '♌︎', '♍︎', '♎︎', '♏︎', '♐︎', '♑︎', '♒︎', '♓︎']

/** Decorative zodiac wheel: real planetary coordinates must come from an ephemeris API. */
function ZodiacWheel({ small = false }: { small?: boolean }) {
  return (
    <svg className="astro-zodiac-wheel" viewBox="0 0 400 400" role={small ? undefined : "img"} aria-hidden={small} aria-label={small ? undefined : "Декоративный зодиакальный круг с Солнцем"}>
      <defs>
        <radialGradient id="astro-sun-glow">
          <stop stopColor="#fff5b8" />
          <stop offset=".18" stopColor="#ffcc57" />
          <stop offset=".48" stopColor="#ad6620" />
          <stop offset="1" stopColor="#2a1707" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="200" cy="200" r="191" stroke="#a67234" strokeWidth="1" fill="#0b0c1a" fillOpacity=".55" />
      {[181, 174, 151, 130, 90, 76].map((radius) => (
        <circle key={radius} cx="200" cy="200" r={radius} stroke="#bc8b43" strokeWidth={radius === 130 ? 1.7 : .65} fill="none" opacity=".74" />
      ))}
      {Array.from({ length: 12 }, (_, index) => {
        const theta = (index * Math.PI) / 6 - Math.PI / 2
        const x1 = 200 + 130 * Math.cos(theta)
        const y1 = 200 + 130 * Math.sin(theta)
        const x2 = 200 + 190 * Math.cos(theta)
        const y2 = 200 + 190 * Math.sin(theta)
        return <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#ae7834" strokeWidth=".8" opacity=".74" />
      })}
      {zodiac.map((sign, index) => {
        const theta = ((index + .5) * Math.PI) / 6 - Math.PI / 2
        return (
          <text key={sign} x={200 + 153 * Math.cos(theta)} y={206 + 153 * Math.sin(theta)}
            textAnchor="middle" fontSize="22" fill="#daa150" fontFamily="DejaVu Sans, Noto Sans Symbols 2, Arial, sans-serif">{sign}</text>
        )
      })}
      <circle cx="200" cy="200" r="73" fill="url(#astro-sun-glow)" opacity=".85" />
      {Array.from({ length: 20 }, (_, index) => (
        <path key={index} d="M200 121 Q208 145 200 160 Q192 145 200 121"
          transform={'rotate(' + index * 18 + ' 200 200)'}
          fill="#b77c31" opacity=".8" />
      ))}
      <circle cx="200" cy="200" r="39" fill="url(#astro-sun-glow)" />
      <circle cx="200" cy="200" r="23" stroke="#f5d28b" strokeWidth="1" fill="none" />
      <circle cx="200" cy="200" r="7" fill="#fff4c6" />
      {!small && <g fill="#e0a54d" opacity=".8">
        <circle cx="56" cy="74" r="3" /><circle cx="330" cy="83" r="2" /><circle cx="74" cy="305" r="2" />
      </g>}
    </svg>
  )
}

function AstroArtwork({ kind }: { kind: AstroKind }) {
  if (kind === 'natal') return <ZodiacWheel small />
  return (
    <svg viewBox="0 0 100 78" className="astro-service-art" aria-hidden="true">
      <g stroke="#ffbd52" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round">
        {kind === 'compatibility' && (
          <>
            <path d="M47 61C30 50 12 37 15 24c3-14 21-14 29-2 7-12 26-11 29 2 3 13-14 26-26 37Z" />
            <path d="M64 61C48 50 30 37 33 24c3-13 21-13 28-1 8-12 26-11 29 2 3 13-14 27-26 36Z" opacity=".85"/>
          </>
        )}
        {kind === 'karma' && (
          <>
            <path d="M50 58C35 45 35 27 50 10c15 17 15 35 0 48Z" fill="#d78a2e" fillOpacity=".17"/>
            <path d="M47 59C27 56 18 42 20 21c21 4 32 17 27 38Z"/>
            <path d="M53 59c20-3 29-17 27-38-21 4-32 17-27 38Z"/>
            <path d="M16 51c9 14 26 18 34 11 8 7 25 3 34-11M38 62h24"/>
            <circle cx="50" cy="41" r="5" fill="#ffc461" stroke="none"/>
          </>
        )}
        {kind === 'year' && (
          <>
            <circle cx="50" cy="43" r="20" fill="#f5a83e" fillOpacity=".2"/>
            <path d="M50 7v11M50 67v7M15 42H4M96 42H85M21 13l8 8M79 13l-8 8" />
            <path d="M18 59q12-8 24 1t26 0q10-8 17 0M14 68q13-8 26 0t28 0q10-6 19 0" />
          </>
        )}
        {kind === 'month' && (
          <>
            <path d="M66 8C40 11 25 31 34 52c6 15 24 18 41 10-16 16-47 15-58-8C4 27 29 4 66 8Z"
              fill="#edb051" fillOpacity=".38" />
            <path d="M68 15l2 6 6 2-6 2-2 6-2-6-6-2 6-2Z" fill="#ffe1a4" stroke="none" />
            <circle cx="83" cy="13" r="2.5" fill="#ffe1a4" stroke="none" />
          </>
        )}
        {kind === 'solar' && (
          <>
            <ellipse cx="50" cy="44" rx="44" ry="13" transform="rotate(-22 50 44)"/>
            <circle cx="51" cy="42" r="25" fill="#a96624" fillOpacity=".5" stroke="#ffd07b"/>
            <path d="M26 49c13 6 34 7 49-2M31 33c11-5 28-5 42 1" opacity=".75"/>
            <path d="M9 61c20 6 69-9 82-31" opacity=".65"/>
          </>
        )}
        {kind === 'lunar' && (
          <>
            <path d="M26 18C9 21 5 50 24 58c8 4 14 2 19-1-22-3-27-24-17-39Z" fill="#edb45d" fillOpacity=".65"/>
            <circle cx="51" cy="38" r="22" fill="#e5ab55" fillOpacity=".35"/>
            <circle cx="51" cy="38" r="21" stroke="#ffd27d" strokeWidth="1"/>
            <path d="M74 18c17 3 21 32 2 40-8 4-14 2-19-1 22-3 27-24 17-39Z" fill="#edb45d" fillOpacity=".65"/>
          </>
        )}
      </g>
      <g fill="#ffe0a0"><circle cx="10" cy="9" r="1.8" /><circle cx="89" cy="64" r="1.2" /><circle cx="75" cy="8" r="1.5" /></g>
    </svg>
  )
}

function isDateValid(value: string): boolean {
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value)
  if (!match) return false
  const day = Number(match[1])
  const month = Number(match[2])
  const year = Number(match[3])
  const date = new Date(year, month - 1, day)
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day
    && date.getTime() <= Date.now()
}

function dateFromPicker(value: string) {
  const parts = value.split('-')
  return parts.length === 3 ? parts[2] + '.' + parts[1] + '.' + parts[0] : ''
}

function countryLabel(code: string): string {
  try {
    return new Intl.DisplayNames(['ru'], { type: 'region' }).of(code) || code
  } catch {
    return code
  }
}

function PlacePicker({
  prefix,
  onSelect,
}: {
  prefix: string
  onSelect?: (place: AstroPlace | null) => void
}) {
  const [city, setCity] = useState('')
  const [selected, setSelected] = useState<AstroPlace | null>(null)
  const [options, setOptions] = useState<AstroPlace[]>([])
  const [activeIndex, setActiveIndex] = useState(0)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const searchVersion = useRef(0)
  const listId = 'astro-places-' + prefix

  // Search while typing, not after a separate button press. Cancel each stale query
  // on edits, selection or unmount; an old response must never replace a new city.
  useEffect(() => {
    const query = city.trim()
    if (selected || query.length < 2) return
    const version = ++searchVersion.current
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setBusy(true)
      setMessage('')
      try {
        const response = await fetch('/mini-app/api/astro/places', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ init_data: getInitData(), query }),
          signal: controller.signal,
        })
        if (controller.signal.aborted || version !== searchVersion.current) return
        if (response.status === 401 || response.status === 403) {
          setMessage('Нет доступа к справочнику городов. Откройте приложение в Telegram.')
          return
        }
        const body = await response.json()
        if (controller.signal.aborted || version !== searchVersion.current) return
        if (!response.ok || !body.ok || !Array.isArray(body.results)) {
          setMessage('Справочник городов недоступен. Можно указать часовой пояс вручную.')
          return
        }
        const places = (body.results as AstroPlace[]).filter((item) =>
          typeof item.place_id === 'number' && Number.isInteger(item.place_id)
          && typeof item.name === 'string' && typeof item.timezone === 'string'
          && typeof item.country_code === 'string'
          && typeof item.latitude === 'number' && typeof item.longitude === 'number'
        )
        setOptions(places)
        setActiveIndex(0)
        if (!places.length) setMessage('Город не найден. Уточните название или страну.')
      } catch {
        if (!controller.signal.aborted && version === searchVersion.current) {
          setMessage('Поиск временно недоступен. Укажите часовой пояс вручную.')
        }
      } finally {
        if (!controller.signal.aborted && version === searchVersion.current) setBusy(false)
      }
    }, 350)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
      searchVersion.current += 1
    }
  }, [city, selected])

  function choosePlace(place: AstroPlace) {
    searchVersion.current += 1
    setSelected(place)
    setCity(place.name + ', ' + countryLabel(place.country_code))
    setOptions([])
    setBusy(false)
    setMessage('Выбран часовой пояс: ' + place.timezone)
    onSelect?.(place)
  }

  return (
    <div className="astro-place-picker">
      <label className="astro-field">
        <MapPin className="astro-field-icon" aria-hidden="true" />
        <span className="astro-field-body">
          <span className="astro-field-label">Место рождения</span>
          <input aria-label={prefix + ': место рождения'} name={prefix + '-place'}
            role="combobox" aria-autocomplete="list" aria-expanded={options.length > 0}
            aria-controls={listId}
            aria-activedescendant={options.length > 0 ? listId + '-' + options[activeIndex].place_id : undefined}
            value={city} autoComplete="off" placeholder="Начните вводить город" maxLength={160}
            onChange={(event) => {
              searchVersion.current += 1
              setCity(event.target.value)
              setSelected(null)
              setOptions([])
              setMessage('')
              setBusy(false)
              onSelect?.(null)
            }}
            onKeyDown={(event) => {
              if (!options.length) return
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setActiveIndex((index) => (index + 1) % options.length)
              } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                setActiveIndex((index) => (index + options.length - 1) % options.length)
              } else if (event.key === 'Enter') {
                event.preventDefault()
                choosePlace(options[activeIndex])
              } else if (event.key === 'Escape') {
                event.preventDefault()
                setOptions([])
              }
            }} />
        </span>
        <Search className="astro-field-trailing" aria-hidden="true" />
      </label>
      <input type="hidden" name={prefix + '-place-id'} value={selected?.place_id ?? ''} />
      {busy && <p className="astro-form-message" role="status">Подбираем город…</p>}
      {options.length > 0 && (
        <div id={listId} className="astro-city-results" role="listbox"
          aria-label={prefix + ': результаты поиска городов'}>
          {options.map((place, index) => (
            <button key={place.place_id} type="button" role="option"
              id={listId + '-' + place.place_id}
              aria-selected={index === activeIndex}
              aria-label={'Выбрать ' + place.name + ', ' + countryLabel(place.country_code)}
              className="astro-city-option" onClick={() => choosePlace(place)}>
              <span>{place.name}, {countryLabel(place.country_code)}</span>
              <small>{place.timezone}</small>
            </button>
          ))}
        </div>
      )}
      {message && <p className="astro-form-message" role="status">{message}</p>}
      <p className="astro-city-credit">Города и страны: © GeoNames (CC BY 4.0)</p>
    </div>
  )
}

function BirthFields({ prefix, heading, requireTimezone = false, onPlaceSelect }: {
  prefix: string
  heading?: string
  requireTimezone?: boolean
  onPlaceSelect?: (place: AstroPlace | null) => void
}) {
  const [date, setDate] = useState('')
  const [birthZone, setBirthZone] = useState('')
  return (
    <div className="astro-birth-fields">
      {heading && <h3 className="astro-form-heading">{heading}</h3>}
      <div className="astro-field">
        <CalendarDays className="astro-field-icon" aria-hidden="true" />
        <span className="astro-field-body">
          <span className="astro-field-label">Дата рождения</span>
          <input aria-label={prefix + ': дата рождения'} name={prefix + '-date'} autoComplete="bday"
            placeholder="ДД.ММ.ГГГГ" inputMode="numeric" maxLength={10} value={date}
            onChange={(event) => setDate(event.target.value)} />
        </span>
        <span className="astro-field-trailing astro-picker-wrap" aria-hidden="true">
          <CalendarDays />
          <input tabIndex={-1} aria-hidden="true" type="date" className="astro-native-picker"
            onChange={(event) => setDate(dateFromPicker(event.target.value))} />
        </span>
      </div>
      <label className="astro-field">
        <Clock3 className="astro-field-icon" aria-hidden="true" />
        <span className="astro-field-body">
          <span className="astro-field-label">Время рождения</span>
          <input aria-label={prefix + ': время рождения'} type="time" name={prefix + '-time'} />
        </span>
        <ChevronDown className="astro-field-trailing" aria-hidden="true" />
      </label>
      <PlacePicker prefix={prefix} onSelect={(place) => {
        setBirthZone(place?.timezone || '')
        onPlaceSelect?.(place)
      }} />
      {requireTimezone && (
        <>
          <label className="astro-field">
            <MapPin className="astro-field-icon" aria-hidden="true" />
            <span className="astro-field-body">
              <span className="astro-field-label">Часовой пояс при рождении (IANA)</span>
              <input aria-label={prefix + ': часовой пояс'} name={prefix + '-timezone'}
                placeholder="Europe/Moscow" autoComplete="off" value={birthZone}
                onChange={(event) => setBirthZone(event.target.value)} />
            </span>
          </label>
          <label className="astro-field">
            <Clock3 className="astro-field-icon" aria-hidden="true" />
            <span className="astro-field-body">
              <span className="astro-field-label">При повторном времени (перевод часов)</span>
              <select aria-label={prefix + ': повторное время'} name={prefix + '-fold'} defaultValue="">
                <option value="">Не знаю / не требуется</option>
                <option value="0">Первое появление времени</option>
                <option value="1">Второе появление времени</option>
              </select>
            </span>
          </label>
        </>
      )}
    </div>
  )
}

function AstroForm({ service, onBack }: { service: AstroService; onBack: () => void }) {
  const [message, setMessage] = useState('')
  const [period, setPeriod] = useState('')
  const [timezoneName, setTimezoneName] = useState(() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' } catch { return 'UTC' }
  })
  const [lunarReport, setLunarReport] = useState<LunarReport | null>(null)
  const [natalReport, setNatalReport] = useState<NatalReport | null>(null)
  const [compatibilityReport, setCompatibilityReport] = useState<CompatibilityReport | null>(null)
  const [birthTimezone, setBirthTimezone] = useState('')
  const [calculating, setCalculating] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    if (['lunar', 'year', 'month', 'solar'].includes(service.id) && !period) {
      setMessage('Выберите период для расчёта.')
      return
    }
    if (service.id === 'lunar') {
      setLunarReport(null)
      setCalculating(true)
      setMessage('Получаем астрономические данные…')
      try {
        const response = await fetch('/mini-app/api/astro/lunar', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ init_data: getInitData(), period, timezone: timezoneName.trim() }),
        })
        if (response.status === 401 || response.status === 403) {
          setMessage('Нет доступа к расчёту. Повторно откройте приложение Telegram.')
          return
        }
        const data = await response.json()
        if (!response.ok || !data.ok || !Array.isArray(data.result?.days)) {
          setMessage(data.message || 'Расчёт сейчас недоступен. Баланс не списан.')
          return
        }
        setLunarReport(data.result as LunarReport)
        setMessage('Лунный календарь рассчитан. Оплата не требуется.')
      } catch {
        setMessage('Не удалось связаться с сервером. Попробуйте ещё раз.')
      } finally {
        setCalculating(false)
      }
      return
    }
    // Never imitate an astronomical calculation or send sensitive birth data to a nonexistent API.
    const dates = service.id === 'compatibility' ? ['person-date', 'partner-date'] : ['person-date']
    if (dates.some((name) => !isDateValid(String(form.get(name) || '')))) {
      setMessage('Укажите корректную дату рождения в формате ДД.ММ.ГГГГ.')
      return
    }
    const places = service.id === 'compatibility' ? ['person-place', 'partner-place'] : ['person-place']
    if (places.some((name) => !String(form.get(name) || '').trim())) {
      setMessage('Укажите место рождения.')
      return
    }
    if (service.id === 'compatibility') {
      const profiles = (['person', 'partner'] as const).map((prefix) => {
        const foldRaw = String(form.get(prefix + '-fold') || '')
        return {
          date: String(form.get(prefix + '-date') || ''),
          time: String(form.get(prefix + '-time') || ''),
          timezone: String(form.get(prefix + '-timezone') || '').trim(),
          ...(foldRaw === '0' || foldRaw === '1' ? { fold: Number(foldRaw) } : {}),
        }
      })
      if (profiles.some((item) => !item.timezone)) {
        setMessage('Укажите часовой пояс рождения каждого человека.')
        return
      }
      setCompatibilityReport(null)
      setCalculating(true)
      setMessage('Рассчитываем межкартные аспекты…')
      try {
        const response = await fetch('/mini-app/api/astro/compatibility', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            init_data: getInitData(), person_a: profiles[0], person_b: profiles[1],
          }),
        })
        if (response.status === 401 || response.status === 403) {
          setMessage('Нет доступа к расчёту. Повторно откройте приложение Telegram.')
          return
        }
        const data = await response.json()
        if (!response.ok || !data.ok || data.result?.schema_version !== 'astro.synastry.facts.v1') {
          setMessage(data.message || 'Расчёт сейчас недоступен. Баланс не списан.')
          return
        }
        setCompatibilityReport(data.result as CompatibilityReport)
        setMessage('Межкартные аспекты рассчитаны. Оплата не требуется.')
      } catch {
        setMessage('Не удалось связаться с сервером. Попробуйте ещё раз.')
      } finally {
        setCalculating(false)
      }
      return
    }
    if (service.id === 'natal') {
      if (!birthTimezone.trim()) {
        setMessage('Укажите часовой пояс места рождения, например Europe/Moscow.')
        return
      }
      const foldRaw = String(form.get('birth-fold') || '')
      setNatalReport(null)
      setCalculating(true)
      setMessage('Рассчитываем положения планет…')
      try {
        const response = await fetch('/mini-app/api/astro/natal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            init_data: getInitData(),
            date: String(form.get('person-date') || ''),
            time: String(form.get('person-time') || ''),
            timezone: birthTimezone.trim(),
            ...(foldRaw === '0' || foldRaw === '1' ? { fold: Number(foldRaw) } : {}),
          }),
        })
        if (response.status === 401 || response.status === 403) {
          setMessage('Нет доступа к расчёту. Повторно откройте приложение Telegram.')
          return
        }
        const data = await response.json()
        if (!response.ok || !data.ok || data.result?.schema_version !== 'astro.natal.facts.v1') {
          setMessage(data.message || 'Расчёт сейчас недоступен. Баланс не списан.')
          return
        }
        setNatalReport(data.result as NatalReport)
        setMessage('Положения рассчитаны. Оплата не требуется.')
      } catch {
        setMessage('Не удалось связаться с сервером. Попробуйте ещё раз.')
      } finally {
        setCalculating(false)
      }
      return
    }
    if (service.id === 'solar' && !String(form.get('solar-place') || '').trim()) {
      setMessage('Укажите место, где вы встретите день рождения в выбранном году.')
      return
    }
    setMessage('Интерфейс подготовлен. Для расчёта требуется подключение астрономического API — данные не отправлены, баланс не списан.')
  }

  return (
    <div className="astro-detail">
      <button type="button" className="astro-back" onClick={onBack}>
        <ArrowLeft size={18} /> Все разделы
      </button>
      <div className="astro-mark"><Sparkles size={28} /></div>
      <div className="astro-kicker"><span /> ASTRO <span /></div>
      <h1 className="astro-detail-title">{service.title}</h1>
      <p className="astro-detail-description">{service.description}</p>
      <div className="astro-wheel-scene" aria-hidden="true">
        <div className="astro-orbit astro-orbit-left">☾</div>
        <ZodiacWheel />
        <div className="astro-orbit astro-orbit-right">♄</div>
      </div>
      <form className="astro-form-panel" noValidate onSubmit={submit}>
        {service.id === 'lunar' ? (
          <>
          <label className="astro-field">
            <CalendarDays className="astro-field-icon" aria-hidden="true" />
            <span className="astro-field-body">
              <span className="astro-field-label">Выберите месяц</span>
              <input aria-label="Месяц календаря" type="month" name="period" required
                value={period} onChange={(event) => setPeriod(event.target.value)} />
            </span>
          </label>
          <label className="astro-field">
            <MapPin className="astro-field-icon" aria-hidden="true" />
            <span className="astro-field-body">
              <span className="astro-field-label">Часовой пояс (IANA)</span>
              <input aria-label="Часовой пояс" name="timezone" value={timezoneName}
                onChange={(event) => setTimezoneName(event.target.value)} placeholder="Europe/Moscow" />
            </span>
          </label>
          </>
        ) : (
          <>
            <BirthFields key={service.id + '-person'} prefix="person"
              heading={service.id === 'compatibility' ? 'Первый человек' : undefined}
              requireTimezone={service.id === 'compatibility'}
              onPlaceSelect={(place) => {
                if (service.id === 'natal') setBirthTimezone(place?.timezone || '')
              }} />
            {service.id === 'compatibility' && <BirthFields prefix="partner" heading="Второй человек" requireTimezone />}
            {service.id === 'natal' && (
              <>
                <label className="astro-field">
                  <MapPin className="astro-field-icon" aria-hidden="true" />
                  <span className="astro-field-body">
                    <span className="astro-field-label">Часовой пояс при рождении (IANA)</span>
                    <input aria-label="Часовой пояс рождения" name="birth-timezone"
                      value={birthTimezone} onChange={(event) => setBirthTimezone(event.target.value)}
                      placeholder="Europe/Moscow" autoComplete="off" />
                  </span>
                </label>
                <label className="astro-field">
                  <Clock3 className="astro-field-icon" aria-hidden="true" />
                  <span className="astro-field-body">
                    <span className="astro-field-label">При повторном времени перевода часов</span>
                    <select aria-label="Повторное местное время" name="birth-fold" defaultValue="">
                      <option value="">Не знаю / не требуется</option>
                      <option value="0">Первое появление времени</option>
                      <option value="1">Второе появление времени</option>
                    </select>
                  </span>
                </label>
                <p className="astro-form-message">
                  Место рождения пока не геокодируется. Укажите его исторический часовой пояс вручную.
                  Для неизвестного времени рождения Луна и аспекты не определяются.
                  Дома и асцендент пока не рассчитываются.
                </p>
              </>
            )}
            {service.id === 'solar' && (
              <label className="astro-field">
                <MapPin className="astro-field-icon" aria-hidden="true" />
                <span className="astro-field-body">
                  <span className="astro-field-label">Место встречи соляра</span>
                  <input aria-label="Место встречи соляра" name="solar-place"
                    autoComplete="off" placeholder="Город, страна" maxLength={160} />
                </span>
                <Search className="astro-field-trailing" aria-hidden="true" />
              </label>
            )}
            {['year', 'month', 'solar'].includes(service.id) && (
              <label className="astro-field">
                <CalendarDays className="astro-field-icon" aria-hidden="true" />
                <span className="astro-field-body">
                  <span className="astro-field-label">{service.id === 'month' ? 'Месяц прогноза' : 'Год прогноза'}</span>
                  <input aria-label="Период прогноза" name="period" required
                    type={service.id === 'month' ? 'month' : 'number'}
                    value={period} onChange={(event) => setPeriod(event.target.value)}
                    placeholder={service.id === 'month' ? undefined : 'ГГГГ'} />
                </span>
              </label>
            )}
          </>
        )}
        <button type="submit" className="astro-submit" disabled={calculating}>
          <Sparkles size={24} aria-hidden="true" />
          <span>{service.id === 'natal' ? 'Построить натальную карту' : service.id === 'lunar' ? 'Открыть лунный календарь' : 'Получить разбор'}</span>
          <ChevronRight size={25} aria-hidden="true" />
        </button>
        {message && <p className="astro-form-message" role="status">{message}</p>}
      </form>
      {compatibilityReport && (
        <div className="astro-lunar-result" aria-label="Рассчитанные межкартные аспекты">
          <h2>Межкартные аспекты</h2>
          <p>Первый человек — {compatibilityReport.person_a.birth_time_known ? 'время рождения известно' : 'время рождения неизвестно'};
            второй человек — {compatibilityReport.person_b.birth_time_known ? 'время рождения известно' : 'время рождения неизвестно'}.
          </p>
          {compatibilityReport.cross_aspects.length ? (
            <ul className="astro-lunar-days">
              {compatibilityReport.cross_aspects.map((item) => (
                <li key={item.person_a_body + '-' + item.person_b_body}>
                  {PLANET_RU[item.person_a_body] || item.person_a_body} (1) —
                  {' '}{PLANET_RU[item.person_b_body] || item.person_b_body} (2):
                  {' '}{ASPECT_RU[item.kind] || item.kind},
                  орбис {item.orb_deg.toFixed(2)}°
                  {item.approximate ? ' · приблизительно' : ''}
                </li>
              ))}
            </ul>
          ) : <p>Значимые межкартные аспекты в заданных орбисах не обнаружены.</p>}
          {compatibilityReport.warnings.map((warning) => <p key={warning}>{warning}</p>)}
        </div>
      )}
      {natalReport && (
        <div className="astro-lunar-result" aria-label="Рассчитанные положения планет">
          <h2>Положения планет</h2>
          <p>Часовой пояс: {natalReport.timezone}. Расчёт на {natalReport.utc_reference} (UTC).
            {natalReport.birth_time_known ? ' Время рождения известно.' : ' Время рождения неизвестно, позиции приближённые.'}
          </p>
          <ul className="astro-lunar-days">
            {Object.entries(natalReport.positions).map(([name, item]) => (
              <li key={name}>
                <strong>{PLANET_RU[name] || name}</strong>: {item.sign} {item.degree_in_sign.toFixed(2)}°
                {item.retrograde ? ' · ретроградность' : ''}
                {item.approximate ? ' · приблизительно' : ''}
              </li>
            ))}
          </ul>
          <h3>Основные аспекты</h3>
          {natalReport.aspects.length ? (
            <ul className="astro-lunar-days">
              {natalReport.aspects.map((item) => (
                <li key={item.a + '-' + item.b}>
                  {PLANET_RU[item.a] || item.a} — {PLANET_RU[item.b] || item.b}: {ASPECT_RU[item.kind] || item.kind}, орбис {item.orb_deg.toFixed(2)}°
                </li>
              ))}
            </ul>
          ) : <p>Точные аспекты не определены либо не обнаружены при выбранных орбисах.</p>}
          {natalReport.warnings.map((warning) => <p key={warning}>{warning}</p>)}
          <p>Это астрономические расчётные данные, а не готовое персональное толкование.</p>
        </div>
      )}
      {lunarReport && (
        <div className="astro-lunar-result" aria-label="Рассчитанный лунный календарь">
          <h2>Лунный календарь за {lunarReport.period}</h2>
          <p>Часовой пояс: {lunarReport.timezone}. Положение Луны указано на 12:00 местного времени; внутри дня оно может измениться.</p>
          <p>Синодический день — полные 24-часовые интервалы после новолуния + 1; это не традиционный лунный день от восхода Луны.</p>
          <ul className="astro-lunar-days">
            {lunarReport.days.map((day) => (
              <li key={day.date}>
                <strong>{day.date}</strong> · {day.moon_sign}, {day.phase}, освещённость {day.illumination_percent}%
                <span> · {day.synodic_day}-й синодический день</span>
                {day.events.length > 0 && <span> · {day.events.join(', ')}</span>}
              </li>
            ))}
          </ul>
          <p>Точное время фаз:</p>
          <ul>{lunarReport.events.map((event) => <li key={event.at_local}>{event.kind} — {event.at_local}</li>)}</ul>
          {lunarReport.ingresses && lunarReport.ingresses.length > 0 && (
            <>
              <p>Точное время перехода Луны между знаками:</p>
              <ul>
                {lunarReport.ingresses.map((event) => (
                  <li key={event.at_local}>
                    {event.from_sign} → {event.to_sign} — {event.at_local}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p>Аспекты, холостая Луна, затмения и традиционные советы по уходу пока не вычисляются.</p>
        </div>
      )}
      <p className="astro-disclaimer">Астрологические интерпретации носят развлекательный характер.</p>
    </div>
  )
}

export function AstroTab() {
  const [selected, setSelected] = useState<AstroKind | null>(null)
  const service = ASTRO_SERVICES.find((item) => item.id === selected)

  return (
    <section className="astro-shell" aria-label="Раздел Astro">
      {service ? (
        <AstroForm key={service.id} service={service} onBack={() => setSelected(null)} />
      ) : (
        <div className="astro-menu">
          <div className="astro-mark"><Sparkles size={28} /></div>
          <div className="astro-kicker"><span /> ASTRO <span /></div>
          <div className="astro-menu-list">
            {ASTRO_SERVICES.map((item) => (
              <button key={item.id} className="astro-menu-card" type="button" onClick={() => setSelected(item.id)}>
                <span className="astro-card-visual"><AstroArtwork kind={item.id} /></span>
                <span className="astro-card-label">
                  <span>{item.title}</span>
                  {item.subtitle && <small>{item.subtitle}</small>}
                </span>
                <ChevronRight className="astro-card-chevron" size={27} strokeWidth={2.5} aria-hidden="true" />
              </button>
            ))}
          </div>
          <div className="astro-menu-footer" aria-hidden="true"><Star size={22} /></div>
        </div>
      )}
    </section>
  )
}
