'use client'

export interface AstroWheelChart {
  bodies: Record<string, { lon: number; retro?: boolean }>
  angles?: { asc: number; mc: number } | null
  cusps?: number[] | null
  aspects?: Array<{ a: string; b: string; aspect: string; orb: number }>
}

const SIGNS = ['♈', '♉', '♊', '♋', '♌', '♍', '♎', '♏', '♐', '♑', '♒', '♓']
const SYMBOLS: Record<string, string> = {
  Sun: '☉', Moon: '☽', Mercury: '☿', Venus: '♀', Mars: '♂',
  Jupiter: '♃', Saturn: '♄', Uranus: '♅', Neptune: '♆', Pluto: '♇',
  TrueNode: '☊', MeanLilith: '⚸',
}
const valid = (x: number) => Number.isFinite(x) && x >= 0 && x < 360
const coordinate = (lon: number, reference: number, radius: number) => {
  const theta = (180 - (lon - reference)) * Math.PI / 180
  return { x: 220 + radius * Math.cos(theta), y: 220 - radius * Math.sin(theta) }
}

export function AstroChartWheel({ chart, label }: { chart: AstroWheelChart; label: string }) {
  const asc = chart.angles && valid(chart.angles.asc) ? chart.angles.asc : null
  const mc = chart.angles && valid(chart.angles.mc) ? chart.angles.mc : null
  const reference = asc ?? 0
  const cusps = chart.cusps?.length === 12 && chart.cusps.every(valid) ? chart.cusps : null
  const bodies = Object.entries(chart.bodies ?? {}).filter(([, p]) => p && valid(p.lon))
  const known = new Map(bodies)
  return (
    <figure className="astro-calculated-chart">
      <svg viewBox="0 0 440 440" role="img" aria-label={label} className="astro-calculated-wheel">
        <title>{label}</title>
        <circle cx="220" cy="220" r="207" fill="#101022" stroke="#dca965" />
        {[195, 161, 111, 83].map(r => <circle key={r} cx="220" cy="220" r={r} fill="none" stroke="#7b614f" />)}
        {SIGNS.map((symbol, index) => {
          const from = coordinate(index * 30, reference, 161)
          const to = coordinate(index * 30, reference, 206)
          const center = coordinate(index * 30 + 15, reference, 181)
          return <g key={index} data-astro-zodiac-sign={index}>
            <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="#ae854f" />
            <text x={center.x} y={center.y + 6} textAnchor="middle" fontSize="20" fill="#f3cd7e">{symbol}</text>
          </g>
        })}
        {cusps?.map((lon, index) => {
          const from = coordinate(lon, reference, 83)
          const to = coordinate(lon, reference, 160)
          const next = cusps[(index + 1) % 12]
          const middle = (lon + ((next - lon + 360) % 360) / 2) % 360
          const labelPosition = coordinate(middle, reference, 99)
          return <g key={index} data-astro-house-cusp={index + 1} data-longitude={lon}>
            <line x1={from.x} y1={from.y} x2={to.x} y2={to.y}
              stroke={index === 0 || index === 6 ? '#f4d58c' : '#827468'} />
            <text x={labelPosition.x} y={labelPosition.y + 3} textAnchor="middle"
              fontSize="10" fill="#ead7b4">{index + 1}</text>
          </g>
        })}
        {(chart.aspects ?? []).filter(a => known.has(a.a) && known.has(a.b)).map((a, index) => {
          const from = coordinate(known.get(a.a)!.lon, reference, 82)
          const to = coordinate(known.get(a.b)!.lon, reference, 82)
          return <line key={index} data-astro-aspect={a.a + '-' + a.b}
            x1={from.x} y1={from.y} x2={to.x} y2={to.y}
            stroke={a.aspect === 'square' || a.aspect === 'opposition' ? '#bb7c70' : '#82afc2'} opacity=".65" />
        })}
        {bodies.map(([name, body]) => {
          const anchor = coordinate(body.lon, reference, 157)
          const destination = coordinate(body.lon, reference, 137)
          return <g key={name} data-astro-body={name} data-longitude={body.lon}>
            <line x1={anchor.x} y1={anchor.y} x2={destination.x} y2={destination.y} stroke="#e2bd86" />
            <circle cx={anchor.x} cy={anchor.y} r="2" fill="#ffe0ac" />
            <text x={destination.x} y={destination.y + 5} fill="#ffdb9f"
              textAnchor="middle" fontSize="17">{SYMBOLS[name] || name.slice(0, 2)}</text>
            <title>{name}: {body.lon.toFixed(2)}°{body.retro ? ', ретроградная' : ''}</title>
          </g>
        })}
        {asc !== null && [['asc', asc], ['dsc', (asc + 180) % 360]].map(([name, lon]) => {
          const p = coordinate(Number(lon), reference, 212)
          return <text key={name} data-astro-angle={name} x={p.x} y={p.y + 3}
            fontSize="10" textAnchor="middle" fill="#fff2cf">{String(name).toUpperCase()}</text>
        })}
        {mc !== null && [['mc', mc], ['ic', (mc + 180) % 360]].map(([name, lon]) => {
          const p = coordinate(Number(lon), reference, 212)
          return <text key={name} data-astro-angle={name} x={p.x} y={p.y + 3}
            fontSize="10" textAnchor="middle" fill="#a9d8ef">{String(name).toUpperCase()}</text>
        })}
      </svg>
      {!cusps || asc === null || mc === null
        ? <figcaption>Дома и углы отсутствуют: нет достоверных данных для Плацидуса.</figcaption>
        : <figcaption>Геоцентрические долготы, дома Плацидуса и фактические аспекты.</figcaption>}
    </figure>
  )
}
