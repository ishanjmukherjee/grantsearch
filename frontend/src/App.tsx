import { useEffect, useState } from 'react'

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
const EXAMPLES = ['soft robotics', 'music and memory', 'Chicago housing segregation', 'black holes', 'theater and social justice']
const PROMPTS = [
  'how to build a moon colony',
  'south asia pig latin',
  'llm-accelerated biology research',
  'photinus carolinus',
  'spectral geometry',
  'functional decision theory',
]
const PROMPT_MS = 3500 // matches the .prompt animation
const DEBOUNCE_MS = 200

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
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [prompt, setPrompt] = useState(0)
  // Prompts rotate until the user clicks or types in the search box, then hold still.
  const [engaged, setEngaged] = useState(false)

  useEffect(() => {
    if (engaged) return
    const timer = setInterval(() => setPrompt((i) => (i + 1) % PROMPTS.length), PROMPT_MS)
    return () => clearInterval(timer)
  }, [engaged])

  useEffect(() => {
    const params = new URLSearchParams()
    if (q.trim()) params.set('q', q.trim())
    if (source) params.set('source', source)
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    const qs = params.toString()
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname)

    if (!q.trim()) {
      setResults(null)
      setLoading(false)
      return
    }
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      setLoading(true)
      try {
        const resp = await fetch(`/api/search?${qs}&n=30`, { signal: controller.signal })
        if (!resp.ok) throw new Error(`The search service returned ${resp.status}.`)
        setResults((await resp.json()).results)
        setError('')
      } catch (e) {
        if (controller.signal.aborted) return
        setError(e instanceof Error ? e.message : 'Search failed.')
      }
      setLoading(false)
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [q, source, from, to])

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
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onPointerDown={() => setEngaged(true)}
              onKeyDown={() => setEngaged(true)}
              aria-label="Search projects"
              autoFocus
            />
            {!q && (
              <span key={prompt} className={engaged ? 'prompt still' : 'prompt'} aria-hidden="true">
                {PROMPTS[prompt]}
              </span>
            )}
          </div>
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
        {results === null && !error && (
          <div className="examples">
            <span>Examples:</span>
            {EXAMPLES.map((ex) => (
              <button key={ex} onClick={() => setQ(ex)}>
                {ex}
              </button>
            ))}
          </div>
        )}
        {results !== null && results.length === 0 && !error && (
          <p className="notice">No projects match. Try different words or widen the filters.</p>
        )}
        {results?.map((p) => <Result key={p.id} project={p} />)}
      </main>
    </div>
  )
}

function Result({ project }: { project: Project }) {
  const { grant, expo } = project
  return (
    <article className="result">
      <div className="tags">
        {grant && <span className="tag surg">SURG {grant.year}</span>}
        {expo.map((e) => (
          <span key={e.id} className="tag expo">
            Expo {e.year}
          </span>
        ))}
      </div>
      <h2>{project.title}</h2>
      {grant && <p className="people">{list(grant.awardees)}</p>}
      {expo.map((e) => (
        <Abstract key={e.id} entry={e} projectTitle={project.title} showTitle={expo.length > 1 || !!grant} />
      ))}
      <div className="links">
        {grant && (
          <a href={grant.url} target="_blank" rel="noreferrer">
            SURG {grant.year} winners list
          </a>
        )}
        {expo.map((e) => (
          <a key={e.id} href={e.url} target="_blank" rel="noreferrer">
            Expo {e.year} program (PDF)
          </a>
        ))}
      </div>
    </article>
  )
}

function Abstract({ entry, projectTitle, showTitle }: { entry: ExpoEntry; projectTitle: string; showTitle: boolean }) {
  const [open, setOpen] = useState(false)
  const advisors = entry.advisor ? `, advised by ${list(entry.advisor.split(/\s*[,;]\s*(?:and\s+)?|\s+and\s+/))}` : ''
  return (
    <section className="abstract">
      {showTitle && entry.title !== projectTitle && (
        <h3>
          Expo {entry.year}: {entry.title}
        </h3>
      )}
      <p className="people">
        {list(entry.presenters)}
        {advisors}
      </p>
      <p className={open ? 'text' : 'text clamped'}>{entry.abstract}</p>
      <button className="more" onClick={() => setOpen(!open)}>
        {open ? 'Hide abstract' : 'Show abstract'}
      </button>
    </section>
  )
}
