import { useEffect, useRef, useState } from 'react'

type Grant = { year: number; awardees: string[]; url: string }
type ExpoEntry = {
  id: string
  year: number
  title: string
  presenters: string[]
  advisor: string | null
  abstract: string
  url: string
}
type Project = { id: string; title: string; grant: Grant | null; expo: ExpoEntry[] }
type Source = '' | 'surg' | 'expo'

const YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
const PROMPTS = [
  'how to build a moon colony',
  'south asia pig latin',
  'llm-accelerated biology research',
  'photinus carolinus',
  'spectral geometry',
  'functional decision theory',
  'dravet syndrome',
  'elon musk',
  'creative writing project for classics majors',
  'astronomy research i can do with public survey data',
]
// After a full pass through PROMPTS, rest on this for a while before the next.
const REST = 'what do you want to research?'
const ROTATION = [...PROMPTS, REST]
const PROMPT_MS = 3500 // matches the .prompt animation
const REST_MS = 12000 // matches the .prompt.rest animation
const DEBOUNCE_MS = 200
const PAGE = 30

function readUrl() {
  const p = new URLSearchParams(window.location.search)
  return {
    q: p.get('q') ?? '',
    source: (p.get('source') ?? '') as Source,
    from: p.get('from') ?? '',
    to: p.get('to') ?? '',
  }
}

function list(names: string[]) {
  if (names.length <= 2) return names.join(' and ')
  return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`
}

export default function App() {
  const initial = readUrl()
  const [q, setQ] = useState(initial.q)
  const [source, setSource] = useState<Source>(initial.source)
  const [from, setFrom] = useState(initial.from)
  const [to, setTo] = useState(initial.to)
  const [results, setResults] = useState<Project[] | null>(null)
  const [more, setMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [prompt, setPrompt] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const sentinel = useRef<HTMLDivElement>(null)
  // The query string the shown results belong to; a later page for an older
  // query is dropped.
  const shown = useRef('')
  const firstLoad = useRef(true)

  useEffect(() => {
    const timer = setTimeout(
      () => setPrompt((i) => (i + 1) % ROTATION.length),
      ROTATION[prompt] === REST ? REST_MS : PROMPT_MS,
    )
    return () => clearTimeout(timer)
  }, [prompt])

  useEffect(() => {
    const params = new URLSearchParams()
    if (q.trim()) params.set('q', q.trim())
    if (source) params.set('source', source)
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    const qs = params.toString()
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname)

    const controller = new AbortController()
    const timer = setTimeout(
      async () => {
        setLoading(true)
        try {
          const resp = await fetch(`/api/search?${qs}${qs ? '&' : ''}n=${PAGE}`, { signal: controller.signal })
          if (!resp.ok) throw new Error(`The search service returned ${resp.status}.`)
          const page = await resp.json()
          // The search controls stay in view, so a new search can start deep
          // in the old list; show the new list from its top.
          if (shown.current !== qs) window.scrollTo(0, 0)
          shown.current = qs
          setResults(page.results)
          setMore(page.more)
          setError('')
        } catch (e) {
          if (controller.signal.aborted) return
          setError(e instanceof Error ? e.message : 'Search failed.')
        }
        setLoading(false)
      },
      // The first load of the page needs no debounce.
      firstLoad.current ? 0 : DEBOUNCE_MS,
    )
    firstLoad.current = false
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [q, source, from, to])

  // Load the next page when the end of the list scrolls into view.
  useEffect(() => {
    const end = sentinel.current
    if (!end || !more || loading || loadingMore || !results) return
    const observer = new IntersectionObserver(
      async ([entry]) => {
        if (!entry.isIntersecting) return
        observer.disconnect()
        const qs = shown.current
        setLoadingMore(true)
        try {
          const resp = await fetch(`/api/search?${qs}${qs ? '&' : ''}n=${PAGE}&offset=${results.length}`)
          if (!resp.ok) throw new Error(`The search service returned ${resp.status}.`)
          const page = await resp.json()
          if (shown.current === qs) {
            setResults([...results, ...page.results])
            setMore(page.more)
          }
        } catch (e) {
          if (shown.current === qs) setError(e instanceof Error ? e.message : 'Loading more results failed.')
        }
        setLoadingMore(false)
      },
      { rootMargin: '800px' },
    )
    observer.observe(end)
    return () => observer.disconnect()
  }, [results, more, loading, loadingMore])

  return (
    <div className="page">
      <header>
        <h1>Wildcat Scholar</h1>
        <p className="lede">
          Northwestern Summer Undergraduate Research Grants (2020-2024) and Undergraduate Research &amp; Arts Expo
          projects (2021-2026). Search by topic, method, field or person.
        </p>
      </header>

      <div className="controls">
        <div className={`searchbox ${loading ? 'loading' : ''}`}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="10.5" cy="10.5" r="6.5" />
            <path d="M15.5 15.5L20 20" />
          </svg>
          <div className="field">
            <input
              ref={input}
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              aria-label="Search projects"
              autoFocus
            />
            {!q && (
              <span key={prompt} className={ROTATION[prompt] === REST ? 'prompt rest' : 'prompt'} aria-hidden="true">
                {ROTATION[prompt]}
              </span>
            )}
          </div>
          {q && (
            <button
              className="clear"
              onClick={() => {
                setQ('')
                input.current?.focus()
              }}
              aria-label="Clear search"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          )}
        </div>
        <div className="filters">
          <div className="segmented" role="group" aria-label="Source">
            {(
              [
                ['', 'All'],
                ['surg', 'SURG grants'],
                ['expo', 'Expo projects'],
              ] as const
            ).map(([value, label]) => (
              <button key={value} className={source === value ? 'on' : ''} onClick={() => setSource(value)}>
                {label}
              </button>
            ))}
          </div>
          <div className="years">
            <select value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From year">
              <option value="">Any year</option>
              {YEARS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
            <span>to</span>
            <select value={to} onChange={(e) => setTo(e.target.value)} aria-label="To year">
              <option value="">Any year</option>
              {YEARS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <main>
        {error && <p className="notice error">{error}</p>}
        {results !== null && results.length === 0 && !error && (
          <p className="notice">No projects match. Try different words or widen the filters.</p>
        )}
        {results?.map((p) => <Result key={p.id} project={p} />)}
        <div ref={sentinel} />
        {loadingMore && <p className="notice">Loading more...</p>}
      </main>
    </div>
  )
}

function Result({ project }: { project: Project }) {
  const { grant, expo } = project
  const parts = sections(expo)
  const programs = new Map(expo.map((e) => [e.url, e.year]))
  return (
    <article className="result">
      <div className="tags">
        {grant && <span className="tag surg">SURG {grant.year}</span>}
        {[...new Set(expo.map((e) => e.year))].map((year) => (
          <span key={year} className="tag expo">
            Expo {year}
          </span>
        ))}
      </div>
      <h2>{project.title}</h2>
      {grant && <p className="people">{list(grant.awardees)}</p>}
      {parts.map((s) => (
        <Abstract key={s.key} section={s} projectTitle={project.title} showTitle={parts.length > 1 || !!grant} />
      ))}
      <div className="links">
        {grant && (
          <a href={grant.url} target="_blank" rel="noreferrer">
            SURG {grant.year} winners list
          </a>
        )}
        {[...programs].map(([url, year]) => (
          <a key={url} href={url} target="_blank" rel="noreferrer">
            Expo {year} program (PDF)
          </a>
        ))}
      </div>
    </article>
  )
}

type Section = { key: string; year: number; title: string; presenters: string[]; advisors: string[]; abstract: string }

// A poster presented by several students is listed once per presenter, usually
// with the same abstract; show each abstract once, with everyone who presented it.
function sections(expo: ExpoEntry[]): Section[] {
  const byAbstract = new Map<string, Section>()
  for (const e of expo) {
    let s = byAbstract.get(e.abstract)
    if (!s) {
      s = { key: e.id, year: e.year, title: e.title, presenters: [], advisors: [], abstract: e.abstract }
      byAbstract.set(e.abstract, s)
    }
    const advisors = e.advisor ? e.advisor.split(/\s*[,;]\s*(?:and\s+)?|\s+and\s+/) : []
    s.presenters = [...new Set([...s.presenters, ...e.presenters])]
    s.advisors = [...new Set([...s.advisors, ...advisors])]
  }
  return [...byAbstract.values()]
}

function Abstract({ section, projectTitle, showTitle }: { section: Section; projectTitle: string; showTitle: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="abstract">
      {showTitle && section.title !== projectTitle && (
        <h3>
          Expo {section.year}: {section.title}
        </h3>
      )}
      <p className="people">
        {list(section.presenters)}
        {section.advisors.length > 0 && `, advised by ${list(section.advisors)}`}
      </p>
      <p className={open ? 'text' : 'text clamped'}>{section.abstract}</p>
      <button className="more" onClick={() => setOpen(!open)}>
        {open ? 'Hide abstract' : 'Show abstract'}
      </button>
    </section>
  )
}
