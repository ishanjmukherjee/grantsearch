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
type Project = { id: string; share: number; title: string; grant: Grant | null; expo: ExpoEntry[] }
type Source = '' | 'surg' | 'expo'

const YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
const PROMPTS = [
  'how to build a moon colony',
  'regional pig latins',
  'llm-accelerated biology research',
  'photinus carolinus',
  'spectral geometry',
  'functional decision theory',
  'dravet syndrome',
  'creative writing project for classics majors',
  'astronomy research i can do with public data',
]
// After a full pass through PROMPTS, rest on this for a while before the next,
// or for good where the prompts run only once.
const REST = 'your idea here'
const ROTATION = [...PROMPTS, REST]
const PROMPT_MS = 3500 // matches the .prompt animation
const REST_MS = 12000 // matches the .prompt.rest animation
const DEBOUNCE_MS = 200
const PAGE = 30
const PAGER_SPAN = 9 // page numbers the pager shows at once; odd, to center the current one
const SITE = 'Wildcat Scholar'
// A share status holds, then fades out with the icon (see .share.fading).
const STATUS_HOLD_MS = 2000
const STATUS_FADE_MS = 600 // matches the .share.fading transitions
// The share icon's press: shrink, then grow back.
const PRESS: Keyframe[] = [{ transform: 'scale(1)' }, { transform: 'scale(0.75)' }, { transform: 'scale(1)' }]
const PRESS_MS = 250

function readUrl() {
  const p = new URLSearchParams(window.location.search)
  return {
    q: p.get('q') ?? '',
    source: (p.get('source') ?? '') as Source,
    from: p.get('from') ?? '',
    to: p.get('to') ?? '',
    page: Math.max(1, Number.parseInt(p.get('page') ?? '') || 1),
  }
}

// What a failed request tells the visitor: only what is known, with the
// details in the console. fetch rejects with a TypeError when no response
// arrives; an error response is thrown as a plain Error.
function failure(e: unknown) {
  console.error(e)
  return e instanceof TypeError ? 'Couldn’t connect. Try again in a moment.' : 'Something went wrong on our end.'
}

function list(names: string[]) {
  if (names.length <= 2) return names.join(' and ')
  return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`
}

export default function App() {
  const [path, setPath] = useState(window.location.pathname)
  useEffect(() => {
    const back = () => setPath(window.location.pathname)
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])
  const page = path.match(/^\/p\/(\d+)\/?$/)
  if (!page) return <Search />
  // Typing on a project page switches to the search page in place, so results
  // show as on the search page; Back returns to the project.
  const search = (q: string) => {
    window.history.pushState(null, '', `/?${new URLSearchParams({ q })}`)
    setPath('/')
  }
  return <ProjectPage key={page[1]} number={page[1]} onSearch={search} />
}

// The search box's rotating example queries, as an index into ROTATION. With
// once, they stop on REST after one pass instead of looping.
function usePrompt(once = false) {
  const [prompt, setPrompt] = useState(0)
  const held = once && ROTATION[prompt] === REST
  useEffect(() => {
    if (held) return
    const timer = setTimeout(
      () => setPrompt((i) => (i + 1) % ROTATION.length),
      ROTATION[prompt] === REST ? REST_MS : PROMPT_MS,
    )
    return () => clearTimeout(timer)
  }, [prompt, held])
  return { prompt, className: held ? 'prompt held' : ROTATION[prompt] === REST ? 'prompt rest' : 'prompt' }
}

function Header({ lede }: { lede?: boolean }) {
  return (
    <header>
      <h1>
        <a href="/">{SITE}</a>
      </h1>
      {lede && (
        <p className="lede">
          Northwestern Summer Undergraduate Research Grants (2020–2024) and Undergraduate Research &amp; Arts Expo
          projects (2021–2026). Search by topic, method, field or person.
        </p>
      )}
    </header>
  )
}

// A shared project's page: the project with its abstracts open, then the
// projects most like it. Searching from here goes to the search page.
function ProjectPage({ number, onSearch }: { number: string; onSearch: (q: string) => void }) {
  const [data, setData] = useState<{ project: Project; similar: Project[] } | null>(null)
  const [error, setError] = useState('')
  const { prompt, className } = usePrompt(true)

  useEffect(() => {
    const controller = new AbortController()
    ;(async () => {
      try {
        const resp = await fetch(`/api/project/${number}`, { signal: controller.signal })
        if (resp.status === 404) {
          setError('No project has this link.')
          return
        }
        if (!resp.ok) throw new Error(`/api/project returned ${resp.status}`)
        const page = await resp.json()
        setData(page)
        document.title = `${page.project.title} — ${SITE}`
        // A link to another of a poster's listings shows the project's own number.
        if (String(page.project.share) !== number) window.history.replaceState(null, '', `/p/${page.project.share}`)
      } catch (e) {
        if (controller.signal.aborted) return
        setError(failure(e))
      }
    })()
    return () => controller.abort()
  }, [number])

  return (
    <div className="page">
      <Header />
      <div className="controls">
        <div className="searchbox">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="10.5" cy="10.5" r="6.5" />
            <path d="M15.5 15.5L20 20" />
          </svg>
          <div className="field">
            <input type="search" value="" onChange={(e) => onSearch(e.target.value)} aria-label="Search projects" />
            <span key={prompt} className={className} aria-hidden="true">
              {ROTATION[prompt]}
            </span>
          </div>
        </div>
      </div>
      <main>
        {error && <p className="notice error">{error}</p>}
        {!data && !error && <p className="notice">Loading…</p>}
        {data && (
          <>
            <Result project={data.project} open />
            {data.similar.length > 0 && <h2 className="section">Similar projects</h2>}
            {data.similar.map((p) => (
              <Result key={p.id} project={p} />
            ))}
          </>
        )}
      </main>
    </div>
  )
}

function Search() {
  const initial = readUrl()
  const [q, setQ] = useState(initial.q)
  const [source, setSource] = useState<Source>(initial.source)
  const [from, setFrom] = useState(initial.from)
  const [to, setTo] = useState(initial.to)
  const [page, setPage] = useState(initial.page)
  const [results, setResults] = useState<Project[] | null>(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { prompt, className } = usePrompt()
  const input = useRef<HTMLInputElement>(null)
  // The query string the shown results belong to.
  const shown = useRef('')
  // Set when the next search should skip the debounce: the page's first load,
  // and moves between pages, which are not typed.
  const instant = useRef(true)

  // The page's URL for the current search at page n; page 1 is left out.
  function href(n: number) {
    const params = new URLSearchParams()
    if (q.trim()) params.set('q', q.trim())
    if (source) params.set('source', source)
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    if (n > 1) params.set('page', String(n))
    const qs = params.toString()
    return qs ? `?${qs}` : window.location.pathname
  }

  // Each page of results is its own history entry, so Back returns to the
  // page before.
  function goTo(n: number) {
    window.history.pushState(null, '', href(n))
    instant.current = true
    setPage(n)
  }

  useEffect(() => {
    const back = () => {
      const url = readUrl()
      setQ(url.q)
      setSource(url.source)
      setFrom(url.from)
      setTo(url.to)
      setPage(url.page)
      instant.current = true
    }
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])

  // Arriving from a project page, which titles the tab after the project.
  useEffect(() => {
    document.title = SITE
  }, [])

  useEffect(() => {
    const url = href(page)
    window.history.replaceState(null, '', url)
    const params = new URLSearchParams(url.startsWith('?') ? url : '')
    params.delete('page')
    params.set('n', String(PAGE))
    params.set('offset', String((page - 1) * PAGE))

    const controller = new AbortController()
    const timer = setTimeout(
      async () => {
        setLoading(true)
        try {
          const resp = await fetch(`/api/search?${params}`, { signal: controller.signal })
          if (!resp.ok) throw new Error(`/api/search returned ${resp.status}`)
          const data = await resp.json()
          // A page past the last, as from a link made when there were more
          // results or fewer to a page, shows the last page instead. The
          // search reruns for it and replaces this URL with its own.
          if (data.results.length === 0 && data.total > 0) {
            instant.current = true
            setPage(Math.ceil(data.total / PAGE))
            return
          }
          // The search controls stay in view, so a new search or page can
          // start deep in the old list; show the new list from its top.
          if (shown.current !== url) window.scrollTo(0, 0)
          shown.current = url
          setResults(data.results)
          setTotal(data.total)
          setError('')
        } catch (e) {
          if (controller.signal.aborted) return
          setError(failure(e))
        }
        setLoading(false)
      },
      instant.current ? 0 : DEBOUNCE_MS,
    )
    instant.current = false
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
    // href reads the search state listed here.
  }, [q, source, from, to, page])

  const pages = Math.ceil(total / PAGE)

  return (
    <div className="page">
      <Header lede />

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
              onChange={(e) => {
                setQ(e.target.value)
                setPage(1)
              }}
              aria-label="Search projects"
              autoFocus
            />
            {!q && (
              <span key={prompt} className={className} aria-hidden="true">
                {ROTATION[prompt]}
              </span>
            )}
          </div>
          {q && (
            <button
              className="clear"
              onClick={() => {
                setQ('')
                setPage(1)
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
              <button key={value} className={source === value ? 'on' : ''} onClick={() => {
                  setSource(value)
                  setPage(1)
                }}>
                {label}
              </button>
            ))}
          </div>
          <div className="years">
            <select value={from} onChange={(e) => {
                setFrom(e.target.value)
                setPage(1)
              }} aria-label="From year">
              <option value="">Any year</option>
              {YEARS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
            <span>to</span>
            <select value={to} onChange={(e) => {
                setTo(e.target.value)
                setPage(1)
              }} aria-label="To year">
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
        {results !== null && total === 0 && !error && (
          <p className="notice">No projects match. Try different words or widen the filters.</p>
        )}
        {results?.map((p) => <Result key={p.id} project={p} />)}
        {pages > 1 && <Pager page={page} pages={pages} href={href} onGo={goTo} />}
      </main>
    </div>
  )
}

// The page numbers the pager shows: the current page, the pages after it in
// order, and before it page 1 and pages evenly spaced from there to the
// current one, so that any earlier page is a click or two away. Half the
// numbers go to each side, or more to one where the other runs out of pages.
function pageNumbers(page: number, pages: number) {
  const half = (PAGER_SPAN - 1) / 2
  const after = Math.min(pages - page, PAGER_SPAN - 1 - Math.min(page - 1, half))
  const before = Math.min(page - 1, PAGER_SPAN - 1 - after)
  const step = (page - 1) / before
  return [
    ...Array.from({ length: before }, (_, i) => Math.round(1 + i * step)),
    page,
    ...Array.from({ length: after }, (_, i) => page + 1 + i),
  ]
}

// Previous and Next around the page numbers.
function Pager({
  page,
  pages,
  href,
  onGo,
}: {
  page: number
  pages: number
  href: (n: number) => string
  onGo: (n: number) => void
}) {
  const numbers = pageNumbers(page, pages)
  // Plain links, so that a page can open in a new tab; a click stays in place.
  const link = (n: number, label: React.ReactNode, props: React.AnchorHTMLAttributes<HTMLAnchorElement> = {}) => (
    <a
      key={typeof label === 'number' ? label : undefined}
      href={href(n)}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
        e.preventDefault()
        onGo(n)
      }}
      {...props}
    >
      {label}
    </a>
  )
  return (
    <nav className="pager" aria-label="Pages">
      {page > 1 ? link(page - 1, 'Previous', { className: 'step', rel: 'prev' }) : <span className="step" />}
      <div className="numbers">
        {numbers.map((n) =>
          n === page ? (
            <span key={n} className="current" aria-current="page">
              {n}
            </span>
          ) : (
            link(n, n, { 'aria-label': `Page ${n}` })
          ),
        )}
      </div>
      {page < pages ? link(page + 1, 'Next', { className: 'step', rel: 'next' }) : <span className="step" />}
    </nav>
  )
}

function Result({ project, open = false }: { project: Project; open?: boolean }) {
  const { grant, expo } = project
  const parts = sections(expo)
  const programs = new Map(expo.map((e) => [e.url, e.year]))

  // The byline under the title: the awardees, or for an Expo-only project
  // everyone who presented it, with each person's advisors when every
  // listing they presented names the same ones.
  const names = grant ? grant.awardees : [...new Set(parts.flatMap((s) => s.students.map((x) => x.name)))]
  const lifted = new Map<string, string[] | null>() // null: advisors vary across their listings
  for (const name of names) {
    const lists = parts.flatMap((s) => s.students.filter((x) => x.name === name).map((x) => x.advisors))
    lifted.set(name, lists.every((l) => sameSet(l, lists[0] ?? [])) ? (lists[0] ?? []) : null)
  }
  const top = names.map((name) => ({ name, advisors: lifted.get(name) ?? [] }))
  const topShared = top.every((x) => sameSet(x.advisors, top[0].advisors)) ? top[0].advisors : null
  const years = new Set(parts.map((s) => s.year))

  return (
    <article className="result">
      <ShareButton project={project} />
      <div className="tags">
        {grant && <span className="tag surg">SURG {grant.year}</span>}
        {[...years].map((year) => (
          <span key={year} className="tag expo">
            Expo {year}
          </span>
        ))}
      </div>
      <h2>
        <a href={`/p/${project.share}`}>{project.title}</a>
      </h2>
      <p className="people">{byline(top)}</p>
      {parts.map((s) => {
        // A section names its students only when they differ from the byline
        // above, and their advisors only when those differ from it too.
        const own =
          !sameSet(
            s.students.map((x) => x.name),
            names,
          ) || s.students.some((x) => lifted.get(x.name) === null)
        const repeat = topShared !== null && s.students.every((x) => sameSet(x.advisors, topShared))
        const people = own ? byline(repeat ? s.students.map((x) => ({ ...x, advisors: [] })) : s.students) : null
        const heading = s.title !== project.title ? `Expo ${s.year}: ${s.title}` : years.size > 1 ? `Expo ${s.year}` : null
        return <Abstract key={s.key} section={s} heading={heading} people={people} open={open} />
      })}
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

type Student = { name: string; advisors: string[] }
type Section = { key: string; year: number; title: string; students: Student[]; abstract: string }

function sameSet(a: string[], b: string[]) {
  return a.length === b.length && a.every((x) => b.includes(x))
}

// Split an advisor list on commas, semicolons and "and", but not inside
// parentheses, which hold an advisor's affiliation.
function advisorNames(advisor: string): string[] {
  const groups: string[] = []
  const masked = advisor.replace(/\([^()]*\)/g, (m) => `\u0000${groups.push(m) - 1}\u0000`)
  return masked
    .split(/\s*[,;]\s*(?:and\s+)?|\s+and\s+/)
    .filter(Boolean)
    .map((name) => name.replace(/\u0000(\d+)\u0000/g, (_, i) => groups[Number(i)]))
}

// A poster presented by several students is listed once per presenter, usually
// with the same abstract; show each abstract once, with everyone who presented
// it. Advisors stay with the students whose listing names them.
function sections(expo: ExpoEntry[]): Section[] {
  const byAbstract = new Map<string, Section>()
  for (const e of expo) {
    let s = byAbstract.get(e.abstract)
    if (!s) {
      s = { key: e.id, year: e.year, title: e.title, students: [], abstract: e.abstract }
      byAbstract.set(e.abstract, s)
    }
    const advisors = e.advisor ? advisorNames(e.advisor) : []
    for (const name of e.presenters) {
      const student = s.students.find((x) => x.name === name)
      if (student) student.advisors = [...new Set([...student.advisors, ...advisors])]
      else s.students.push({ name, advisors })
    }
  }
  return [...byAbstract.values()]
}

// "X and Y, advised by A" when every student has the same advisors; otherwise
// each student's advisors in parentheses after their name, students with
// advisors first so that a trailing parenthesis never reads as the team's.
function byline(students: Student[]) {
  if (students.every((x) => sameSet(x.advisors, students[0].advisors))) {
    const advisors = students[0].advisors
    return list(students.map((x) => x.name)) + (advisors.length ? `, advised by ${list(advisors)}` : '')
  }
  const ordered = [...students.filter((x) => x.advisors.length), ...students.filter((x) => !x.advisors.length)]
  return list(ordered.map((x) => (x.advisors.length ? `${x.name} (advised by ${list(x.advisors)})` : x.name)))
}

// Opens the share sheet on touch devices, which have one; elsewhere copies the link.
function ShareButton({ project }: { project: Project }) {
  const [status, setStatus] = useState({ text: '', n: 0, fading: false })
  const timers = useRef<number[]>([])
  function show(text: string) {
    // A new message starts over.
    setStatus((s) => ({ text, n: s.n + 1, fading: false }))
    timers.current.forEach(clearTimeout)
    timers.current = [
      window.setTimeout(() => setStatus((s) => ({ ...s, fading: true })), STATUS_HOLD_MS),
      window.setTimeout(() => setStatus((s) => ({ ...s, text: '', fading: false })), STATUS_HOLD_MS + STATUS_FADE_MS),
    ]
  }
  async function share(e: React.MouseEvent<HTMLButtonElement>) {
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      e.currentTarget.animate(PRESS, { duration: PRESS_MS, easing: 'ease-out' })
    }
    const url = `${window.location.origin}/p/${project.share}`
    if (navigator.share && window.matchMedia('(pointer: coarse)').matches) {
      await navigator.share({ title: project.title, url }).catch(() => {}) // dismissed
      return
    }
    try {
      await navigator.clipboard.writeText(url)
      show('Link copied!')
    } catch {
      show('Could not copy the link')
    }
  }
  return (
    <div className={status.fading ? 'share fading' : 'share'}>
      {status.text && (
        <span key={status.n} className="status" role="status">
          {status.text}
        </span>
      )}
      <button onClick={share} aria-label="Share" title="Share">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 15V3M8 7l4-4 4 4" />
          <path d="M8 10H6a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1h-2" />
        </svg>
      </button>
    </div>
  )
}

function Abstract({
  section,
  heading,
  people,
  open: initiallyOpen,
}: {
  section: Section
  heading: string | null
  people: string | null
  open: boolean
}) {
  const [open, setOpen] = useState(initiallyOpen)
  return (
    <section className="abstract">
      {heading && <h3>{heading}</h3>}
      {people && <p className="people">{people}</p>}
      <p className={open ? 'text' : 'text clamped'}>{section.abstract}</p>
      <button className="more" onClick={() => setOpen(!open)}>
        {open ? 'Hide abstract' : 'Show abstract'}
      </button>
    </section>
  )
}
