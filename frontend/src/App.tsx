import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'

// A poster's listing: a poster presented by several students may be listed
// once per presenter.
type Listing = {
  id: string
  title: string | null // null when the program prints none (the 2003 Symposium)
  presenters: string[]
  advisors: string[]
  abstract: string
  url: string // the program PDF, opening at the abstract's page
  page: number | null
  // Where the abstract is from when the program printed none (Expo 2020's
  // one project never posted online has the student's abstract from elsewhere).
  abstract_source: { name: string; url: string } | null
}
// One source's account of the project: a SURG or AY URG grant (with its
// students and advisors), an Expo or Symposium poster (with its listings), or
// an honors thesis or NURJ paper (with its students, advisors and abstract,
// which a thesis list may not give).
type ProjectRecord = {
  id: string
  source: string
  kind: 'grant' | 'presentation' | 'thesis' | 'paper'
  year: number
  title: string | null
  url: string
  students?: string[]
  advisors?: string[]
  listings?: Listing[]
  abstract?: string | null
  department?: string
  academic_year?: string
  report?: string | null // a Computer Science thesis's technical report number
}
// title is null when none of the project's sources prints one; made_title is
// then a plain description of it written from its abstract, if it has one.
type Project = {
  id: string
  share: number
  title: string | null
  made_title: string | null
  records: ProjectRecord[]
}
type ExpoEntry = Listing & { year: number; source: string }
type Source = '' | 'surg' | 'expo' | 'theses'

// The years any record falls in: the oldest thesis is from 1980.
const FIRST_YEAR = 1980
const LAST_YEAR = 2026
// Newest first, as the year dropdowns list them.
const YEARS = Array.from({ length: LAST_YEAR - FIRST_YEAR + 1 }, (_, i) => LAST_YEAR - i)
// What tags and links call each source.
const SOURCE_NAMES: Record<string, string> = {
  surg: 'SURG',
  ay_urg: 'AY URG',
  expo: 'Expo',
  symposium: 'Symposium',
  theses: 'Thesis',
  nurj: 'NURJ',
}
// A department as a thesis tag names it.
const DEPARTMENTS: Record<string, string> = {
  'Mathematical Methods in the Social Sciences': 'MMSS',
}
const department = (r: ProjectRecord) => DEPARTMENTS[r.department!] ?? r.department!
// Ordered to onboard visitors quickly: most start typing after two or three
// prompts, so the first few do most of the work and should show the range of
// the index.
const PROMPTS = [
  'how to build a moon colony', // a playful hook; ambitious, plain-language queries work
  'creative writing project for classics majors', // humanities right away; project-style
  'dravet syndrome', // a specific medical term
  'chad mirkin lab', // searching by person or lab
  'research interviewing doctors', // describes a method, not a topic
  'spectral geometry', // a math term
  'biology in extreme environments', // a topic described in plain words
  'music research using old recordings', // the arts; finds Mahler's piano rolls without the word "recording"
  'regional pig latin', // whimsy in the middle
  'llm-accelerated biology research', // AI crossover
  'photinus carolinus', // a species name
  'astronomy research i can do with public data', // "i can do" leads into REST
]
// After a full pass through PROMPTS, rest on this for a while before the next,
// or for good where the prompts run only once.
const REST = 'your idea here'
const ROTATION = [...PROMPTS, REST]
const PROMPT_MS = 3500 // matches the .prompt animation
const REST_MS = 12000 // matches the .prompt.rest animation
const DEBOUNCE_MS = 200
const MAX_QUERY = 2000 // the longest q the backend accepts; a longer query is cut to it
const PAGE = 30
const PAGER_SPAN = 9 // the most page numbers the pager shows at once, where they fit
const SITE = 'Prowl'
const CLAMP_LINES = 5 // matches the line-clamp of .abstract .text.clamped
// A share status holds, then fades out with the icon (see .share.fading).
const STATUS_HOLD_MS = 2000
const STATUS_FADE_MS = 600 // matches the .share.fading transitions
// The share icon's press: shrink, then grow back.
const PRESS: Keyframe[] = [{ transform: 'scale(1)' }, { transform: 'scale(0.75)' }, { transform: 'scale(1)' }]
const PRESS_MS = 250

// The search in the page's URL. A value the controls can't show, as from an
// old or hand-edited link, is dropped rather than sent on to the backend.
// A search: its query, filters and page of results.
type Query = { q: string; source: Source; from: string; to: string; page: number }

function readUrl(): Query {
  const p = new URLSearchParams(window.location.search)
  const source = p.get('source')
  const year = (y: string | null) => (YEARS.some((v) => String(v) === y) ? y! : '')
  const page = Number.parseInt(p.get('page') ?? '')
  return {
    q: p.get('q') ?? '',
    source: source === 'surg' || source === 'expo' || source === 'theses' ? source : '',
    from: year(p.get('from')),
    to: year(p.get('to')),
    // A page so large its offset loses precision would be sent in exponent form.
    page: page >= 1 && Number.isSafeInteger(page * PAGE) ? page : 1,
  }
}

// The page's URL for a search at page n; page 1 is left out.
function searchUrl({ q, source, from, to }: Query, n: number) {
  const params = new URLSearchParams()
  if (q.trim()) params.set('q', q.trim())
  if (source) params.set('source', source)
  if (from) params.set('from', from)
  if (to) params.set('to', to)
  if (n > 1) params.set('page', String(n))
  const qs = params.toString()
  return qs ? `?${qs}` : window.location.pathname
}

// A request that got no response, or one from a proxy that couldn't reach
// the server, as while it restarts on a deploy.
class Unreachable extends Error {}

// A fetch whose failure to get a response is told apart from errors thrown
// later, in our own code. The caller checks for an abort itself.
async function get(url: string, signal: AbortSignal) {
  let resp: Response
  try {
    resp = await fetch(url, { signal })
  } catch (e) {
    throw new Unreachable(`${url} got no response`, { cause: e })
  }
  if ([502, 503, 504].includes(resp.status)) throw new Unreachable(`${url} returned ${resp.status}`)
  return resp
}

// What a failed request tells the visitor: only what is known, with the
// details in the console.
function failure(e: unknown) {
  console.error(e)
  return e instanceof Unreachable ? 'Couldn’t connect. Try again in a moment.' : 'Something went wrong on our end.'
}

// The quoted phrases of a query, found as the backend finds them (see
// search.py): ignoring case and runs of whitespace, and not inside a longer
// word at either end. One pattern matches any of them, for highlighting.
const QUOTED = /["\u201c\u201d]([^"\u201c\u201d]*)["\u201c\u201d]/g
const WORD = /[\p{L}\p{N}_]/u

function quotePattern(query: string): RegExp | null {
  const phrases = [...query.matchAll(QUOTED)].flatMap(([, phrase]) => {
    const words = phrase.split(/\s+/).filter(Boolean)
    if (!words.length) return []
    const start = WORD.test(words[0][0]) ? '(?<![\\p{L}\\p{N}_])' : ''
    const end = WORD.test(words[words.length - 1].slice(-1)) ? '(?![\\p{L}\\p{N}_])' : ''
    return [start + words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+') + end]
  })
  return phrases.length ? new RegExp(phrases.join('|'), 'giu') : null
}

// The quoted phrases to highlight in results, if any.
const Quotes = createContext<RegExp | null>(null)

// What a project whose sources print no title is called: on the result
// itself, as its heading; inside a project, a section says only "untitled".
const UNTITLED = 'Untitled Project'
// A project's name where it has no printed title: "Untitled Project", and
// what it is about when it has a made title.
const untitled = (project: Project) => (project.made_title ? `${UNTITLED}: ${project.made_title}` : UNTITLED)

// Text with each quoted phrase in it marked, as find in page does.
function Marked({ text }: { text: string }) {
  const pattern = useContext(Quotes)
  if (!pattern) return text
  const parts: React.ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(pattern)) {
    if (!m[0]) continue
    parts.push(text.slice(last, m.index), <mark key={m.index}>{m[0]}</mark>)
    last = m.index + m[0].length
  }
  parts.push(text.slice(last))
  return parts
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

// Whether the page's tab is in view, and how many times it has come back into
// view.
function useVisible() {
  const [visible, setVisible] = useState(!document.hidden)
  const [returns, setReturns] = useState(0)
  useEffect(() => {
    const update = () => {
      setVisible(!document.hidden)
      if (!document.hidden) setReturns((n) => n + 1)
    }
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  return { visible, returns }
}

// The search box's rotating example queries, as an index into ROTATION. With
// once, they stop on REST after one pass instead of looping. They pause while
// the tab is out of view or the prompt is not shown, so a visitor who opens
// the page in the background still sees the first prompts first. The CSS
// animation keeps running while the tab is hidden and ends faded out, so on
// each return the key changes to remount the prompt, and resumed swaps in an
// animation that holds it in full view for the restarted timer before fading
// it out, rather than fading in a prompt already read.
function usePrompt({ once = false, shown = true } = {}) {
  const { visible, returns } = useVisible()
  const [{ prompt, since }, setPrompt] = useState({ prompt: 0, since: returns })
  const held = once && ROTATION[prompt] === REST
  useEffect(() => {
    if (held || !visible || !shown) return
    const timer = setTimeout(
      () => setPrompt({ prompt: (prompt + 1) % ROTATION.length, since: returns }),
      ROTATION[prompt] === REST ? REST_MS : PROMPT_MS,
    )
    return () => clearTimeout(timer)
  }, [prompt, held, visible, shown, returns])
  const resumed = returns !== since ? ' resumed' : ''
  return {
    prompt,
    key: held ? `${prompt}` : `${prompt}.${returns}`,
    className: held ? 'prompt held' : ROTATION[prompt] === REST ? `prompt rest${resumed}` : `prompt${resumed}`,
  }
}

function Header({ lede }: { lede?: boolean }) {
  return (
    <header>
      <h1>
        <a href="/">{SITE}</a>
      </h1>
      {lede && (
        <p className="lede">
          Decades of Northwestern undergraduate research:{' '}
          <a href="https://undergradresearch.northwestern.edu/funding/surg/">SURG</a> grants{' '}
          <span className="nowrap">(2007–2024)</span>,{' '}
          <a href="https://undergradresearch.northwestern.edu/share/expo/">Expo</a> projects{' '}
          <span className="nowrap">(2003–2026)</span> and honors theses <span className="nowrap">(1980–2026)</span>.
          Search by topic, method, field or person.
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
  useEffect(() => {
    const controller = new AbortController()
    ;(async () => {
      try {
        const resp = await get(`/api/project/${number}`, controller.signal)
        if (resp.status === 404) {
          setError('No project has this link.')
          return
        }
        if (!resp.ok) throw new Error(`/api/project returned ${resp.status}`)
        const page = await resp.json()
        setData(page)
        document.title = `${page.project.title ?? untitled(page.project)} — ${SITE}`
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
        <SearchBox value="" onChange={onSearch} once />
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
  const [query, setQuery] = useState(readUrl)
  const { q, source, from, to, page } = query
  const [results, setResults] = useState<Project[] | null>(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // The quoted phrases of the query the shown results are for, not of one
  // still being typed.
  const [quotes, setQuotes] = useState<RegExp | null>(null)
  // The query string the shown results belong to.
  const shown = useRef('')
  // Set when the next search should skip the debounce: the page's first load,
  // and moves between pages, which are not typed.
  const instant = useRef(true)

  // A changed query or filter starts again from the first page.
  function change(edit: Partial<Omit<Query, 'page'>>) {
    setQuery((s) => ({ ...s, ...edit, page: 1 }))
  }

  function setPage(n: number) {
    instant.current = true
    setQuery((s) => ({ ...s, page: n }))
  }

  // Each page of results is its own history entry, so Back returns to the
  // page before.
  function goTo(n: number) {
    window.history.pushState(null, '', searchUrl(query, n))
    setPage(n)
  }

  useEffect(() => {
    const back = () => {
      instant.current = true
      setQuery(readUrl())
    }
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])

  // Arriving from a project page, which titles the tab after the project.
  useEffect(() => {
    document.title = SITE
  }, [])

  useEffect(() => {
    const url = searchUrl({ q, source, from, to, page }, page)
    window.history.replaceState(null, '', url)
    const params = new URLSearchParams(url.startsWith('?') ? url : '')
    // The URL keeps the whole query; the search uses only its start.
    const used = q.trim().slice(0, MAX_QUERY)
    if (used) params.set('q', used)
    params.delete('page')
    params.set('n', String(PAGE))
    params.set('offset', String((page - 1) * PAGE))

    const controller = new AbortController()
    const timer = setTimeout(
      async () => {
        setLoading(true)
        try {
          const resp = await get(`/api/search?${params}`, controller.signal)
          if (!resp.ok) throw new Error(`/api/search returned ${resp.status}`)
          const data = await resp.json()
          // A page past the last, as from a link made when there were more
          // results or fewer to a page, shows the last page instead. The
          // search reruns for it and replaces this URL with its own.
          if (data.results.length === 0 && data.total > 0) {
            setPage(Math.ceil(data.total / PAGE))
            return
          }
          // The search controls stay in view, so a new search or page can
          // start deep in the old list; show the new list from its top.
          if (shown.current !== url) window.scrollTo(0, 0)
          shown.current = url
          setResults(data.results)
          setQuotes(quotePattern(used))
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
  }, [q, source, from, to, page])

  const pages = Math.ceil(total / PAGE)
  const length = q.trim().length

  return (
    <div className="page">
      <Header lede />

      <div className="controls">
        <SearchBox value={q} onChange={(value) => change({ q: value })} loading={loading} autoFocus />
        <div className="filters">
          <div className="segmented" role="group" aria-label="Source">
            {(
              [
                ['', 'All'],
                ['surg', 'SURG grants'],
                ['expo', 'Expo projects'],
                ['theses', 'Theses'],
              ] as const
            ).map(([value, label]) => (
              <button key={value} className={source === value ? 'on' : ''} onClick={() => change({ source: value })}>
                {label}
              </button>
            ))}
          </div>
          <div className="years">
            <YearSelect value={from} onChange={(value) => change({ from: value })} label="From year" />
            <span>to</span>
            <YearSelect value={to} onChange={(value) => change({ to: value })} label="To year" />
          </div>
        </div>
      </div>

      <main>
        {length > MAX_QUERY && (
          <p className="notice">
            Only the first {MAX_QUERY.toLocaleString('en-US')} characters of a search are used. This one is{' '}
            {length.toLocaleString('en-US')}.
          </p>
        )}
        {error && <p className="notice error">{error}</p>}
        {results !== null && total === 0 && !error && (
          <p className="notice">No projects match. Try different words or widen the filters.</p>
        )}
        <Quotes.Provider value={quotes}>{results?.map((p) => <Result key={p.id} project={p} />)}</Quotes.Provider>
        {pages > 1 && <Pager page={page} pages={pages} href={(n) => searchUrl(query, n)} onGo={goTo} />}
      </main>
    </div>
  )
}

// The search box, with the rotating example queries while it is empty. With
// once, they stop after one pass, as usePrompt's once does.
function SearchBox({
  value,
  onChange,
  loading = false,
  autoFocus = false,
  once = false,
}: {
  value: string
  onChange: (value: string) => void
  loading?: boolean
  autoFocus?: boolean
  once?: boolean
}) {
  const { prompt, key, className } = usePrompt({ once, shown: !value })
  const input = useRef<HTMLInputElement>(null)
  return (
    <div className={loading ? 'searchbox loading' : 'searchbox'}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="M15.5 15.5L20 20" />
      </svg>
      <div className="field">
        <input
          ref={input}
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label="Search projects"
          autoFocus={autoFocus}
        />
        {!value && (
          <span key={key} className={className} aria-hidden="true">
            {ROTATION[prompt]}
          </span>
        )}
      </div>
      {value && (
        <button
          className="clear"
          onClick={() => {
            onChange('')
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
  )
}

function YearSelect({ value, onChange, label }: { value: string; onChange: (value: string) => void; label: string }) {
  return (
    <span className="select">
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        <option value="">Any year</option>
        {YEARS.map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>
    </span>
  )
}

// The page numbers the pager shows: the current page, the pages after it in
// order, and before it page 1 and pages evenly spaced from there to the
// current one, so that any earlier page is a click or two away. Half the
// span goes to each side (the odd one after), or more to one side where the
// other runs out of pages.
function pageNumbers(page: number, pages: number, span: number) {
  const half = Math.floor((span - 1) / 2)
  const after = Math.min(pages - page, span - 1 - Math.min(page - 1, half))
  const before = Math.min(page - 1, span - 1 - after)
  const step = (page - 1) / before
  return [
    ...Array.from({ length: before }, (_, i) => Math.round(1 + i * step)),
    page,
    ...Array.from({ length: after }, (_, i) => page + 1 + i),
  ]
}

// Prev and Next around as many page numbers as fit in one row.
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
  const [span, setSpan] = useState(PAGER_SPAN)
  const nav = useRef<HTMLElement>(null)
  // Every number is as wide as the widest page's, so how many fit does not
  // depend on which are shown. Counts again when the row's width changes.
  useLayoutEffect(() => {
    const row = nav.current!
    const fit = () => {
      const [prev, numbers, next] = [...row.children] as HTMLElement[]
      const slot = numbers.firstElementChild as HTMLElement
      const gap = parseFloat(getComputedStyle(row).columnGap)
      const numberGap = parseFloat(getComputedStyle(numbers).columnGap)
      // The side columns are equal, so each must hold the wider label.
      const side = (el: HTMLElement) => {
        const style = getComputedStyle(el)
        return el.offsetWidth + parseFloat(style.marginLeft) + parseFloat(style.marginRight)
      }
      const room = row.clientWidth - 2 * Math.max(side(prev), side(next)) - 2 * gap
      const fits = Math.floor((room + numberGap) / (slot.offsetWidth + numberGap))
      setSpan(Math.max(1, Math.min(PAGER_SPAN, fits)))
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(row)
    return () => observer.disconnect()
  }, [pages])
  const numbers = pageNumbers(page, pages, span)
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
  // Shown dimmed at either end, so the row has the same shape on every page.
  const disabled = (label: string) => (
    <span className="step disabled" aria-disabled="true">
      {label}
    </span>
  )
  return (
    <nav ref={nav} className="pager" aria-label="Pages">
      {page > 1
        ? link(page - 1, 'Prev', { className: 'step', rel: 'prev', 'aria-label': 'Previous page' })
        : disabled('Prev')}
      <div className="numbers" style={{ '--digits': String(pages).length } as React.CSSProperties}>
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
      {page < pages ? link(page + 1, 'Next', { className: 'step', rel: 'next' }) : disabled('Next')}
    </nav>
  )
}

function Result({ project, open = false }: { project: Project; open?: boolean }) {
  const grants = project.records.filter((r) => r.kind === 'grant')
  const theses = project.records.filter((r) => r.kind === 'thesis')
  const papers = project.records.filter((r) => r.kind === 'paper')
  const expo: ExpoEntry[] = project.records
    .flatMap((r) => (r.listings ?? []).map((e) => ({ ...e, year: r.year, source: r.source })))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  const parts = sections(expo)
  // A thesis or paper whose abstract a poster above already shows (an Expo
  // poster often prints the thesis's, or most of it) shows only its heading.
  const written = writings(theses, papers).map((w) =>
    parts.some((s) => sameAbstract(s.abstract, w.abstract)) ? { ...w, abstract: '' } : w,
  )

  // The byline under the title: the awardees; for a project without a grant,
  // everyone who presented it; or for a thesis or paper alone, its authors.
  // Each person's advisors are named with them when every listing they
  // presented names the same ones.
  const names = grants.length
    ? [...new Set(grants.flatMap((g) => g.students ?? []))]
    : parts.length
      ? [...new Set(parts.flatMap((s) => s.students.map((x) => x.name)))]
      : [...new Set(written.flatMap((w) => w.students.map((x) => x.name)))]
  const pool = parts.length ? parts : written
  const lifted = new Map<string, string[] | null>() // null: advisors vary across their listings
  for (const name of names) {
    const lists = pool.flatMap((s) => s.students.filter((x) => x.name === name).map((x) => x.advisors))
    // Someone no listing names, as the awardee of a grant without posters,
    // has the advisors the grant names.
    if (!lists.length) {
      lifted.set(name, grants.find((g) => g.students?.includes(name))?.advisors ?? [])
      continue
    }
    lifted.set(name, lists.every((l) => sameSet(l, lists[0] ?? [])) ? (lists[0] ?? []) : null)
  }
  const top = names.map((name) => ({ name, advisors: lifted.get(name) ?? [] }))
  const topShared = top.every((x) => sameSet(x.advisors, top[0].advisors)) ? top[0].advisors : null
  const years = [...new Map(parts.map((s) => [`${s.source} ${s.year}`, s])).values()]
  const multiple = parts.length + written.length > 1
  // Every listing gets its own link, also where its abstract is shown merged
  // with another's; a year's listings are told apart by their pages.
  const listed = new Map<number, number>()
  for (const e of expo) listed.set(e.year, (listed.get(e.year) ?? 0) + 1)

  // A section names its students only when they differ from the byline
  // above, and their advisors only when those differ from it too.
  function people(students: Student[]) {
    const own =
      !sameSet(
        students.map((x) => x.name),
        names,
      ) ||
      students.some(
        (x) => lifted.get(x.name) === null || (x.advisors.length > 0 && !sameSet(x.advisors, lifted.get(x.name)!)),
      )
    const repeat = topShared !== null && students.every((x) => sameSet(x.advisors, topShared))
    return own ? byline(repeat ? students.map((x) => ({ ...x, advisors: [] })) : students) : null
  }

  return (
    <article className="result">
      <ShareButton project={project} />
      <div className="tags">
        {grants.map((g) => (
          <span key={g.id} className="tag surg">
            {SOURCE_NAMES[g.source]} {g.year}
          </span>
        ))}
        {years.map((s) => (
          <span key={`${s.source} ${s.year}`} className="tag expo">
            {SOURCE_NAMES[s.source]} {s.year}
          </span>
        ))}
        {theses.map((t) => (
          <span key={t.id} className="tag thesis">
            {department(t)} thesis {t.year}
          </span>
        ))}
        {papers.map((x) => (
          <span key={x.id} className="tag nurj">
            NURJ {x.year}
          </span>
        ))}
      </div>
      <h2>
        <a href={`/p/${project.share}`}>
          {project.title ? <Marked text={project.title} /> : <span className="untitled">{untitled(project)}</span>}
        </a>
      </h2>
      <p className="people">
        <Marked text={byline(top)} />
      </p>
      {parts.map((s) => {
        const heading =
          s.title !== project.title
            ? `${SOURCE_NAMES[s.source]} ${s.year}: ${s.title ?? 'untitled'}`
            : years.length > 1 || written.length
              ? `${SOURCE_NAMES[s.source]} ${s.year}`
              : null
        return <Abstract key={s.key} section={s} heading={heading} people={people(s.students)} open={open} />
      })}
      {written.map((w) => {
        const heading = !sameTitle(w.title, project.title) ? `${w.label}: ${w.title}` : multiple ? w.label! : null
        const who = people(w.students)
        if (!heading && !who && !w.abstract) return null
        return <Abstract key={w.key} section={w} heading={heading} people={who} open={open} />
      })}
      <div className="links">
        {grants.map((g) => (
          <a key={g.id} href={g.url} target="_blank" rel="noreferrer">
            {SOURCE_NAMES[g.source]} {g.year} winners <ExternalIcon />
          </a>
        ))}
        {expo.map((e) => (
          <a key={e.id} href={e.url} target="_blank" rel="noreferrer">
            {SOURCE_NAMES[e.source]} {e.year} listing
            {listed.get(e.year)! > 1 && e.page ? `, p. ${e.page}` : ''} <PdfIcon /> <ExternalIcon />
          </a>
        ))}
        {theses.map((t) => (
          <a key={t.id} href={t.url} target="_blank" rel="noreferrer">
            {thesisLink(t)} {t.url.endsWith('.pdf') && <PdfIcon />} <ExternalIcon />
          </a>
        ))}
        {papers.map((x) => (
          <a key={x.id} href={x.url} target="_blank" rel="noreferrer">
            NURJ {x.year} <ExternalIcon />
          </a>
        ))}
        {parts
          .filter((s) => s.abstractSource)
          .map((s) => (
            <a key={`${s.key}-abstract`} href={s.abstractSource!.url} target="_blank" rel="noreferrer">
              Abstract: {s.abstractSource!.name} <ExternalIcon />
            </a>
          ))}
      </div>
    </article>
  )
}

// Where a thesis's link goes: its technical report, the MMSS library (behind
// a Northwestern login), or its department's list of honors theses.
function thesisLink(t: ProjectRecord) {
  if (t.report) return `Technical report ${t.report}`
  if (department(t) === 'MMSS') return 'MMSS thesis library (Northwestern login)'
  const [from, to] = t.academic_year!.split('-')
  return `${t.department} honors theses, ${from}–${to.slice(2)}`
}

// Whether two titles are one however they are capitalized or punctuated.
function sameTitle(a: string | null, b: string | null) {
  const key = (t: string | null) => (t?.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []).join(' ')
  return key(a) === key(b)
}

// Whether two abstracts are one, perhaps one trimmed from the other: most of
// the shorter's word trigrams are in the longer.
function sameAbstract(a: string, b: string) {
  const [x, y] = [trigrams(a), trigrams(b)].sort((p, q) => p.size - q.size)
  if (!x.size) return false
  let shared = 0
  for (const t of x) if (y.has(t)) shared++
  return shared / x.size >= 0.6
}

function trigrams(text: string) {
  const words = text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []
  return new Set(words.slice(2).map((w, i) => `${words[i]} ${words[i + 1]} ${w}`))
}

// A project's theses and papers as sections: a thesis two departments list
// (or one library catalogues twice) is one thesis, shown once with every
// department that lists it and the first abstract any listing gives.
function writings(theses: ProjectRecord[], papers: ProjectRecord[]): Section[] {
  const people = (r: ProjectRecord) => (r.students ?? []).map((name) => ({ name, advisors: r.advisors ?? [] }))
  const out: Section[] = []
  if (theses.length) {
    const t = theses[0]
    const students: Student[] = []
    for (const r of theses)
      for (const x of people(r)) {
        const student = students.find((y) => y.name === x.name || sameName(y.name, x.name))
        if (student) student.advisors = [...new Set([...student.advisors, ...x.advisors])]
        else students.push(x)
      }
    const departments = [...new Set(theses.map(department))]
    out.push({
      key: t.id,
      year: t.year,
      source: t.source,
      title: t.title,
      students,
      abstract: theses.find((r) => r.abstract)?.abstract ?? '',
      abstractSource: null,
      label: `${list(departments)} thesis ${t.year}`,
    })
  }
  for (const x of papers)
    out.push({
      key: x.id,
      year: x.year,
      source: x.source,
      title: x.title,
      students: people(x),
      abstract: x.abstract ?? '',
      abstractSource: null,
      label: `NURJ ${x.year}`,
    })
  return out
}

// Whether two spellings of a name are one person's as listings write them:
// the same surname and one first name the start of the other ("Chris Bull",
// "Christopher Bull").
function sameName(a: string, b: string) {
  const [fa, ...ra] = a.split(' ')
  const [fb, ...rb] = b.split(' ')
  return ra.at(-1) === rb.at(-1) && (fa.startsWith(fb) || fb.startsWith(fa))
}

type Student = { name: string; advisors: string[] }
type Section = {
  key: string
  year: number
  source: string
  title: string | null
  students: Student[]
  abstract: string // '' where a thesis or paper has none
  abstractSource: ExpoEntry['abstract_source']
  label?: string // a thesis's or paper's name for itself in a heading
}

function sameSet(a: string[], b: string[]) {
  return a.length === b.length && a.every((x) => b.includes(x))
}

// A poster presented by several students is listed once per presenter, usually
// with the same abstract; show each abstract once, with everyone who presented
// it. The API gives versions of one abstract one text (see the backend's
// projects.fold), so the same text is the same abstract. Advisors stay with
// the students whose listing names them.
function sections(expo: ExpoEntry[]): Section[] {
  const byAbstract = new Map<string, Section>()
  for (const e of expo) {
    let s = byAbstract.get(e.abstract)
    if (!s) {
      s = {
        key: e.id,
        year: e.year,
        source: e.source,
        title: e.title,
        students: [],
        abstract: e.abstract,
        abstractSource: e.abstract_source,
      }
      byAbstract.set(e.abstract, s)
    }
    const advisors = e.advisors
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
      await navigator.share({ title: project.title ?? untitled(project), url }).catch(() => {}) // dismissed
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

function ExternalIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </svg>
  )
}

// Adobe's small PDF file icon, which Adobe offers for links to PDFs
// (adobe.com/legal/permissions/icons-web-logos.html), redrawn from its 24px
// original: the page, its fold and Acrobat's mark, traced as one line. Drawn
// in the link's color, not Adobe's.
function PdfIcon() {
  return (
    <svg className="pdf" viewBox="3.5 0.5 17 22" role="img" aria-label="(PDF)">
      <path d="M5.5 0.5H15.7L20.5 5.3V20.5A2 2 0 0 1 18.5 22.5H5.5A2 2 0 0 1 3.5 20.5V2.5A2 2 0 0 1 5.5 0.5Z" />
      <path className="fold" d="M15.7 0.5L20.5 5.3" />
      <path className="mark" d="M10.1 14.3C9.65 14.76 8.39 15.24 7.8 15.38C7.21 15.51 6.69 15.41 6.55 15.1C6.41 14.79 6.59 13.93 6.95 13.53C7.31 13.12 8.15 12.89 8.7 12.7C9.25 12.51 9.75 13 10.22 12.4C10.7 11.8 11.56 9.87 11.57 9.12C11.59 8.38 10.23 8.62 10.3 7.92C10.37 7.23 11.58 5 12 4.95C12.42 4.9 12.77 6.78 12.8 7.62C12.83 8.47 12.17 9.2 12.2 10C12.23 10.8 12.77 12.11 12.97 12.43C13.18 12.74 13.13 12.07 13.4 11.9C13.67 11.73 13.83 11.27 14.6 11.4C15.37 11.53 17.58 12.32 18 12.7C18.42 13.08 17.6 13.55 17.1 13.7C16.6 13.85 15.8 13.8 15 13.6C14.2 13.4 13.05 12.66 12.3 12.5C11.55 12.34 10.84 12.32 10.47 12.62C10.11 12.93 10.55 13.84 10.1 14.3Z" />
    </svg>
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
  // Whether the abstract runs past the clamp, so that it has more to show.
  const [overflows, setOverflows] = useState(false)
  const text = useRef<HTMLParagraphElement>(null)
  const body = useRef<HTMLSpanElement>(null)
  const quotes = useContext(Quotes)
  // Counts the abstract's own lines, not the inline toggle's, and counts
  // again when the card's width changes.
  useLayoutEffect(() => {
    if (!body.current) return
    const measure = () => {
      const tops = new Set([...body.current!.getClientRects()].map((r) => Math.round(r.top)))
      setOverflows(tops.size > CLAMP_LINES)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(text.current!)
    return () => observer.disconnect()
  }, [section.abstract])
  // Like find in page, open an abstract whose first quoted phrase is cut off.
  useLayoutEffect(() => {
    const mark = text.current?.querySelector('mark')
    if (mark && mark.getBoundingClientRect().bottom > text.current!.getBoundingClientRect().bottom) setOpen(true)
  }, [quotes])
  return (
    <section className="abstract">
      {heading && (
        <h3>
          <Marked text={heading} />
        </h3>
      )}
      {people && (
        <p className="people">
          <Marked text={people} />
        </p>
      )}
      {section.abstract && (
        <div className="clamp">
          <p ref={text} className={open ? 'text' : 'text clamped'}>
            <span ref={body}>
              <Marked text={section.abstract} />
            </span>
            {open && overflows && (
              <>
                {' '}
                <button className="more" aria-expanded="true" onClick={() => setOpen(false)}>
                  Show less
                </button>
              </>
            )}
          </p>
          {!open && overflows && (
            <button className="more fade" aria-expanded="false" onClick={() => setOpen(true)}>
              Show more
            </button>
          )}
        </div>
      )}
    </section>
  )
}
