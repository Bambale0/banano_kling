'use client'

import { useState, type FormEvent } from 'react'
import {
  ArrowLeft, CalendarDays, ChevronDown, ChevronRight, Clock3,
  MapPin, Search, Sparkles, Star,
} from 'lucide-react'
import './astro-tab.css'

type AstroKind = 'natal' | 'compatibility' | 'karma' | 'year' | 'month' | 'solar' | 'lunar'

interface AstroService {
  id: AstroKind
  title: string
  subtitle?: string
  description: string
}

export const ASTRO_SERVICES: readonly AstroService[] = [
  { id: 'natal', title: 'Натальная карта', description: 'Полный анализ вашей личности, талантов, кармы и жизненного пути' },
  { id: 'compatibility', title: 'Совместимость', description: 'Астрологический разбор отношений по данным двух людей' },
  { id: 'karma', title: 'Кармический разбор', description: 'Лунные узлы, жизненные темы и символические уроки' },
  { id: 'year', title: 'Годовой прогноз', description: 'Астрологические транзиты и тенденции на выбранный год' },
  { id: 'month', title: 'Гороскоп на месяц', description: 'Персональные астрологические тенденции месяца' },
  { id: 'solar', title: 'Соляр', subtitle: 'Личный год от дня рождения', description: 'Карта солнечного возвращения на новый личный год' },
  { id: 'lunar', title: 'Лунный календарь', description: 'Фазы Луны и ключевые лунные события месяца' },
]

const zodiac = ['♈', '♉', '♊', '♋', '♌', '♍', '♎', '♏', '♐', '♑', '♒', '♓']

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
            textAnchor="middle" fontSize="22" fill="#daa150" fontFamily="Georgia,serif">{sign}</text>
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

function BirthFields({ prefix, heading }: { prefix: string; heading?: string }) {
  const [date, setDate] = useState('')
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
      <label className="astro-field">
        <MapPin className="astro-field-icon" aria-hidden="true" />
        <span className="astro-field-body">
          <span className="astro-field-label">Место рождения</span>
          <input aria-label={prefix + ': место рождения'} name={prefix + '-place'}
            autoComplete="off" placeholder="Город, страна" maxLength={160} />
        </span>
        <Search className="astro-field-trailing" aria-hidden="true" />
      </label>
    </div>
  )
}

function AstroForm({ service, onBack }: { service: AstroService; onBack: () => void }) {
  const [message, setMessage] = useState('')
  const [period, setPeriod] = useState('')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    if (['lunar', 'year', 'month', 'solar'].includes(service.id) && !period) {
      setMessage('Выберите период для расчёта.')
      return
    }
    // Never imitate an astronomical calculation or send sensitive birth data to a nonexistent API.
    if (service.id !== 'lunar') {
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
          <label className="astro-field">
            <CalendarDays className="astro-field-icon" aria-hidden="true" />
            <span className="astro-field-body">
              <span className="astro-field-label">Выберите месяц</span>
              <input aria-label="Месяц календаря" type="month" name="period" required
                value={period} onChange={(event) => setPeriod(event.target.value)} />
            </span>
          </label>
        ) : (
          <>
            <BirthFields key={service.id + '-person'} prefix="person" heading={service.id === 'compatibility' ? 'Первый человек' : undefined} />
            {service.id === 'compatibility' && <BirthFields prefix="partner" heading="Второй человек" />}
            {['year', 'month', 'solar'].includes(service.id) && (
              <label className="astro-field">
                <CalendarDays className="astro-field-icon" aria-hidden="true" />
                <span className="astro-field-body">
                  <span className="astro-field-label">{service.id === 'month' ? 'Месяц прогноза' : 'Год прогноза'}</span>
                  <input aria-label="Период прогноза" name="period" required
                    type={service.id === 'month' ? 'month' : 'number'}
                    min={service.id === 'month' ? undefined : 1900}
                    max={service.id === 'month' ? undefined : 2200}
                    value={period} onChange={(event) => setPeriod(event.target.value)}
                    placeholder={service.id === 'month' ? undefined : 'ГГГГ'} />
                </span>
              </label>
            )}
          </>
        )}
        <button type="submit" className="astro-submit">
          <Sparkles size={24} aria-hidden="true" />
          <span>{service.id === 'natal' ? 'Построить натальную карту' : service.id === 'lunar' ? 'Открыть лунный календарь' : 'Получить разбор'}</span>
          <ChevronRight size={25} aria-hidden="true" />
        </button>
        {message && <p className="astro-form-message" role="status">{message}</p>}
      </form>
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
