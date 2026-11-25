import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'
import filed from './disciplines.json'
import wordmark from './wordmark.json'

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
  // The listing's poster, slides or other document from ForagerOne, hosted at
  // files.prowl.nu (Expo 2020's and 2022's).
  pdf: { url: string; kind: 'poster' | 'slides' | 'document' } | null
}
// One source's account of the project: a SURG or AY URG grant (with its
// students and advisors), an Expo or Symposium poster (with its listings), or
// an honors thesis or NURJ paper (with its students, advisors and abstract,
// which a thesis list may not give), or a Leopold fellowship on a faculty
// member's project (with its fellows as students and that faculty as advisors).
type ProjectRecord = {
  id: string
  source: string
  kind: 'grant' | 'presentation' | 'thesis' | 'paper' | 'fellowship'
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
  pdf?: string | null // a NURJ paper's PDF or an MMSS thesis's paper, hosted at files.prowl.nu
  // A fellowship's project as its entry describes it, where it prints no
  // title or beside one; its abstract is what the faculty member wrote in
  // offering the project, and offered the document that is from.
  description?: string | null
  offered?: string | null
}
// title is null when none of the project's sources prints one; made_title is
// then a plain description of it written from its abstract, if it has one.
type Project = {
  id: string
  share: number
  title: string | null
  made_title: string | null
  disciplines: string[] // the ids of those it is filed under, the main one first
  records: ProjectRecord[]
}
type ExpoEntry = Listing & { year: number; source: string }
// The source filters, as the row of them reads.
const SOURCES = [
  ['surg', 'SURG grants'],
  ['expo', 'Expo projects'],
  ['theses', 'Theses'],
  ['nurj', 'NURJ papers'],
  ['leopold', 'Leopold fellows'],
] as const
type Source = (typeof SOURCES)[number][0]

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
  leopold: 'Leopold',
}
// A department as a thesis tag names it.
const DEPARTMENTS: Record<string, string> = {
  'Mathematical Methods in the Social Sciences': 'MMSS',
}
const department = (r: ProjectRecord) => DEPARTMENTS[r.department!] ?? r.department!
// The disciplines projects are filed under, area by area: the backend's list
// (pipeline.disciplines), which checks this copy against its own.
type Discipline = { id: string; label: string; area: string }
const DISCIPLINES: Discipline[] = (filed as string[][]).map(([id, label, area]) => ({ id, label, area }))
const DISCIPLINE = new Map(DISCIPLINES.map((d) => [d.id, d]))
const AREAS = [...new Set(DISCIPLINES.map((d) => d.area))]
// The ids of each area's disciplines, and each area by its name in a link,
// which the backend spells the same way (pipeline.disciplines).
const MEMBERS = new Map(AREAS.map((area) => [area, DISCIPLINES.filter((d) => d.area === area).map((d) => d.id)]))
const areaSlug = (area: string) => area.toLowerCase().replace(/[^a-z]+/g, '-')
const AREA = new Map(AREAS.map((area) => [areaSlug(area), area]))

// What is chosen, as the chips that say it: an area whose disciplines are
// all chosen is one chip under its name, and any other discipline its own.
// They are in the order chosen, an area where the first of its was.
type Choice = { key: string; label: string; area: string | null; ids: string[] }
function choices(chosen: string[]): Choice[] {
  const out: Choice[] = []
  const whole = new Set<string>()
  for (const id of chosen) {
    const { label, area } = DISCIPLINE.get(id)!
    const ids = MEMBERS.get(area)!
    if (!ids.every((d) => chosen.includes(d))) out.push({ key: id, label, area: null, ids: [id] })
    else if (!whole.has(area)) {
      whole.add(area)
      out.push({ key: `area ${area}`, label: area, area, ids })
    }
  }
  return out
}
const OFFERED = 12 // the most disciplines the row offers beside those chosen
// How many projects the index holds, which the server writes in the page's
// head; NaN where another server serves the page, as Vite's does.
const PROJECTS = Number(document.querySelector<HTMLMetaElement>('meta[name="projects"]')?.content)
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
// How far a click beside an abstract's Show more still counts as on it.
// Unlike a CSS hit area, which would lie over the text and stop a drag from
// ending on it, this takes plain clicks only and leaves a drag to select.
const MORE_REACH_X = 8
const MORE_REACH_Y = 10
// A share status holds, then fades out with the icon (see .share.fading).
const STATUS_HOLD_MS = 2000
const STATUS_FADE_MS = 600 // matches the .share.fading transitions
// The share icon's press: shrink, then grow back.
const PRESS: Keyframe[] = [{ transform: 'scale(1)' }, { transform: 'scale(0.75)' }, { transform: 'scale(1)' }]
const PRESS_MS = 250

// The search in the page's URL. A value the controls can't show, as from an
// old or hand-edited link, is dropped rather than sent on to the backend.
// A search: its query, filters and page of results.
type Query = { q: string; sources: Source[]; from: string; to: string; disciplines: string[]; page: number }

function readUrl(): Query {
  const p = new URLSearchParams(window.location.search)
  const sources = p.getAll('source')
  const year = (y: string | null) => (YEARS.some((v) => String(v) === y) ? y! : '')
  const page = Number.parseInt(p.get('page') ?? '')
  return {
    q: p.get('q') ?? '',
    sources: SOURCES.map(([s]) => s).filter((s) => sources.includes(s)),
    from: year(p.get('from')),
    to: year(p.get('to')),
    disciplines: [
      ...new Set(
        [...p].flatMap(([name, value]) =>
          name === 'discipline' && DISCIPLINE.has(value) ? [value] : name === 'area' ? (MEMBERS.get(AREA.get(value)!) ?? []) : [],
        ),
      ),
    ],
    // A page so large its offset loses precision would be sent in exponent form.
    page: page >= 1 && Number.isSafeInteger(page * PAGE) ? page : 1,
  }
}

// The page's URL for a search at page n; page 1 is left out. A wholly chosen
// area is named once, as area, in place of each of its disciplines.
function searchUrl({ q, sources, from, to, disciplines }: Query, n: number) {
  const params = new URLSearchParams()
  if (q.trim()) params.set('q', q.trim())
  for (const s of sources) params.append('source', s)
  if (from) params.set('from', from)
  if (to) params.set('to', to)
  for (const c of choices(disciplines)) params.append(c.area ? 'area' : 'discipline', c.area ? areaSlug(c.area) : c.key)
  if (n > 1) params.set('page', String(n))
  const qs = params.toString()
  return qs ? `?${qs}` : window.location.pathname
}

// What the query log (the backend's querylog) is told about this tab.
//
// A visit is one tab's stay: a random id kept in sessionStorage, which ends
// with the tab, so the log can tell which searches and clicks were one
// visitor's without knowing who they are or following them to another day.
// Its searches are numbered in order, also across the tab's page loads.
// Where the browser refuses storage, both last until the page is left.
const kept = new Map<string, string>()

function recall(key: string) {
  try {
    return window.sessionStorage.getItem(key) ?? kept.get(key) ?? null
  } catch {
    return kept.get(key) ?? null
  }
}

function keep(key: string, value: string) {
  kept.set(key, value)
  try {
    window.sessionStorage.setItem(key, value)
  } catch {
    // Kept in memory alone.
  }
}

function visit() {
  let id = recall('visit')
  if (!id) {
    // randomUUID needs a secure page, which a phone on the dev server lacks.
    const bytes = () =>
      Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0'))
    id = crypto.randomUUID?.() ?? bytes().join('')
    keep('visit', id)
  }
  return id
}

function nextSeq() {
  const seq = Number(recall('seq') ?? 0) + 1
  keep('seq', String(seq))
  return seq
}

// Whether this browser is one the site is built and tested on, whose searches
// the log sets apart from visitors': opening /?internal=1 once marks it so
// from then on, and /?internal=0 unmarks it.
const internal = (() => {
  try {
    const mark = new URLSearchParams(window.location.search).get('internal')
    if (mark === '1') window.localStorage.setItem('internal', '1')
    if (mark === '0') window.localStorage.removeItem('internal')
    return window.localStorage.getItem('internal') === '1'
  } catch {
    return false
  }
})()

// The headers that tell the log whose request this is.
function visitHeaders(): Record<string, string> {
  return internal ? { 'X-Visit': visit(), 'X-Internal': '1' } : { 'X-Visit': visit() }
}

// Why a search was sent: the page opened on it (as from a link), the query
// was typed, a filter was changed, a page of results was chosen, or the
// visitor went back or forward to it.
type Cause = 'load' | 'type' | 'filter' | 'page' | 'back'
// The cause of the search the search page opens on: typing on a project page
// switches to it with what was typed.
let arrival: Cause = 'load'
// The number of the search whose results are on screen, if any are.
let shownSeq: number | null = null

// Where a result is on the page: among a search's results (with the search's
// number and the result's rank in the whole ranking, from 1), the project its
// page is for, or one of the similar projects under it (with its rank there).
type Place = { project: string; on: 'search' | 'project' | 'similar'; seq?: number; rank?: number }

// Tells the log what a visitor did with a result. A beacon is still sent
// when the click itself leaves the page.
function report(
  kind: 'click' | 'expand' | 'share',
  place: Place,
  more: { link?: string; record?: string } = {},
) {
  const body = JSON.stringify({ kind, visit: visit(), internal, ...place, ...more })
  try {
    if (navigator.sendBeacon?.('/api/event', body)) return
  } catch {
    // Try a plain request instead.
  }
  fetch('/api/event', { method: 'POST', body, keepalive: true }).catch(() => {})
}

// A request that got no response, or one from a proxy that couldn't reach
// the server, as while it restarts on a deploy.
class Unreachable extends Error {}

// A fetch whose failure to get a response is told apart from errors thrown
// later, in our own code. The caller checks for an abort itself.
async function get(url: string, signal: AbortSignal, headers: Record<string, string> = {}) {
  let resp: Response
  try {
    resp = await fetch(url, { signal, headers: { ...visitHeaders(), ...headers } })
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

// The search page's filters, for the disciplines and tags on its results.
// For disciplines: those chosen, the link to the search with one chosen or
// dropped, and what a click on that link does in place. For tags: the same
// three, where a tag's filter is its source alone and its year alone. Null
// on a project's page.
const Filter = createContext<{
  chosen: string[]
  href: (id: string) => string
  toggle: (id: string) => void
  tagged: (source: Source, year: number) => boolean
  tagHref: (source: Source, year: number) => string
  tagToggle: (source: Source, year: number) => void
} | null>(null)

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
    arrival = 'type'
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

// The site's name as drawn letters, not type: design/wordmark/draw.py draws
// them and writes the outline. It takes the text colour, and its name is the
// heading's and the link's.
function Wordmark() {
  return (
    <svg className="wordmark" viewBox={`0 0 ${wordmark.width} ${wordmark.height}`} role="img" aria-label={SITE}>
      <path d={wordmark.path} fillRule="evenodd" />
    </svg>
  )
}

function Header({ lede }: { lede?: boolean }) {
  return (
    <header>
      <h1>
        <a href="/">
          <Wordmark />
        </a>
      </h1>
      {lede && (
        <p className="lede">
          {/* The index's size, rounded down to a hundred so that it holds
              as projects are added. */}
          {PROJECTS >= 100 && `${(Math.floor(PROJECTS / 100) * 100).toLocaleString('en-US')} `}
          Northwestern undergraduate research projects since {FIRST_YEAR}:{' '}
          <a href="https://undergradresearch.northwestern.edu/funding/surg/">SURG</a> grants,{' '}
          <a href="https://undergradresearch.northwestern.edu/share/expo/">Expo</a> projects, honors theses,{' '}
          <a href="https://thenurj.com/">NURJ</a> papers, and{' '}
          <a href="https://historicalstudies.northwestern.edu/fellowships/leopold-fellows/">Leopold</a> fellowships. Search
          by topic, method, field, or person.
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
            <Result project={data.project} place={{ on: 'project' }} open />
            {data.similar.length > 0 && <h2 className="section">Similar projects</h2>}
            {data.similar.map((p, i) => (
              <Result key={p.id} project={p} place={{ on: 'similar', rank: i + 1 }} />
            ))}
          </>
        )}
      </main>
    </div>
  )
}

function Search() {
  const [query, setQuery] = useState(readUrl)
  const { q, sources, from, to, disciplines, page } = query
  const [results, setResults] = useState<Project[] | null>(null)
  // The disciplines the shown results' search offers, those none of its
  // results are in, and whether it had no query.
  const [offered, setOffered] = useState<{ ids: string[]; empty: string[]; browsing: boolean }>({
    ids: [],
    empty: [],
    browsing: true,
  })
  // Whether the list of every discipline is open. New results then leave the
  // page where it is, so the list does not move while it is chosen from.
  const listOpen = useRef(false)
  const onListOpen = useCallback((open: boolean) => {
    listOpen.current = open
  }, [])
  // The search the shown results answer: its number, and how many results
  // rank above the first shown.
  const [listed, setListed] = useState({ seq: 0, offset: 0 })
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
  // Why the next search is sent, for the query log.
  const cause = useRef<Cause>(arrival)

  // A changed query or filter starts again from the first page.
  function change(edit: Partial<Omit<Query, 'page'>>) {
    cause.current = 'q' in edit ? 'type' : 'filter'
    setQuery((s) => ({ ...s, ...edit, page: 1 }))
  }

  function setPage(n: number) {
    instant.current = true
    cause.current = 'page'
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
      cause.current = 'back'
      setQuery(readUrl())
    }
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])

  // Arriving from a project page, which titles the tab after the project.
  useEffect(() => {
    document.title = SITE
    arrival = 'load'
  }, [])

  useEffect(() => {
    const url = searchUrl({ q, sources, from, to, disciplines, page }, page)
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
          const seq = nextSeq()
          const sent: Record<string, string> = { 'X-Seq': String(seq), 'X-Cause': cause.current }
          if (shownSeq !== null) sent['X-Shown'] = String(shownSeq)
          const resp = await get(`/api/search?${params}`, controller.signal, sent)
          if (!resp.ok) throw new Error(`/api/search returned ${resp.status}`)
          const data = await resp.json()
          // A page past the last, as from a link made when there were more
          // results or fewer to a page, shows the last page instead. The
          // search reruns for it and replaces this URL with its own.
          if (data.results.length === 0 && data.total > 0) {
            setPage(Math.ceil(data.total / PAGE))
            return
          }
          // The search box stays in view, so a new search or page can
          // start deep in the old list; show the new list from its top.
          if (shown.current !== url && !listOpen.current) window.scrollTo(0, 0)
          shown.current = url
          shownSeq = seq
          setListed({ seq, offset: (page - 1) * PAGE })
          setResults(data.results)
          setOffered({ ids: data.disciplines, empty: data.empty, browsing: !used })
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
  }, [q, sources, from, to, disciplines, page])

  const pages = Math.ceil(total / PAGE)
  const length = q.trim().length
  const toggled = (id: string) => (disciplines.includes(id) ? disciplines.filter((d) => d !== id) : [...disciplines, id])
  // The sources with one chosen or dropped, in the order of their chips.
  const switched = (s: Source) => SOURCES.map(([v]) => v).filter((v) => sources.includes(v) !== (v === s))
  // A tag's filter: its source alone and its year alone, or neither if the
  // search is filtered to just that already.
  const tagged = (s: Source, year: number) =>
    sources.length === 1 && sources[0] === s && from === String(year) && to === String(year)
  const tag = (s: Source, year: number) =>
    tagged(s, year) ? { sources: [], from: '', to: '' } : { sources: [s], from: String(year), to: String(year) }
  const filter = {
    chosen: disciplines,
    href: (id: string) => searchUrl({ ...query, disciplines: toggled(id) }, 1),
    toggle: (id: string) => change({ disciplines: toggled(id) }),
    tagged,
    tagHref: (s: Source, year: number) => searchUrl({ ...query, ...tag(s, year) }, 1),
    tagToggle: (s: Source, year: number) => change(tag(s, year)),
  }

  return (
    <div className="page">
      <Header lede />

      <div className="controls">
        <SearchBox value={q} onChange={(value) => change({ q: value })} loading={loading} autoFocus />
      </div>
      <div className="filters">
        <div className="sources" role="group" aria-label="Sources">
          {SOURCES.map(([value, label]) => {
            const on = sources.includes(value)
            return (
              <button
                key={value}
                className={on ? 'chip on' : 'chip'}
                aria-pressed={on}
                onClick={() => change({ sources: switched(value) })}
              >
                {label}
              </button>
            )
          })}
        </div>
        <div className="years">
          <YearSelect value={from} onChange={(value) => change({ from: value })} label="From year" />
          <span>to</span>
          <YearSelect value={to} onChange={(value) => change({ to: value })} label="To year" />
        </div>
      </div>

      <Disciplines
        offered={offered.ids}
        browsing={offered.browsing}
        empty={offered.empty}
        chosen={disciplines}
        onChange={(value) => change({ disciplines: value })}
        onOpen={onListOpen}
      />

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
        <Quotes.Provider value={quotes}>
          <Filter.Provider value={filter}>
            {results?.map((p, i) => (
              <Result key={p.id} project={p} place={{ on: 'search', seq: listed.seq, rank: listed.offset + i + 1 }} />
            ))}
          </Filter.Provider>
        </Quotes.Provider>
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

// The disciplines the row offers beside those chosen: the likeliest for the
// search, as the backend orders them. With no query no result says which are
// likely, and that order is of size, so the row takes the largest discipline
// of each area before the second largest of any, to show the range of the
// index.
function offers(offered: string[], chosen: string[], browsing: boolean) {
  let rest = offered.filter((d) => DISCIPLINE.has(d))
  if (browsing) {
    const met = new Map<string, number>()
    const turns = rest.map((d, i) => {
      const area = DISCIPLINE.get(d)!.area
      const turn = met.get(area) ?? 0
      met.set(area, turn + 1)
      return { d, turn, i }
    })
    rest = turns.sort((a, b) => a.turn - b.turn || a.i - b.i).map((x) => x.d)
  }
  return rest.filter((d) => !chosen.includes(d)).slice(0, OFFERED)
}

const LIST_MARGIN = 12 // kept clear between the open list and the window's bottom

// The discipline filter: a row of chips, each choosing or dropping one
// discipline, and a button that opens the list of them all by area, where an
// area's name chooses or drops all of its disciplines at once. Results are of
// any of the disciplines chosen. The list draws a discipline none of the
// search's results are in as an outline; the row offers only those some are
// in.
//
// The row is one line: what is chosen (see choices), then the disciplines
// the search offers. With a mouse, an offered chip that doesn't fit in what
// is left of the line is left out, and a later, shorter one may take its
// place; chosen chips that don't fit are counted in a chip after those that
// do, which opens the list, where all that is chosen shows. Under a finger
// the row scrolls sideways instead, fading at an edge that hides more.
function Disciplines({
  offered,
  browsing,
  empty,
  chosen,
  onChange,
  onOpen,
}: {
  offered: string[]
  browsing: boolean
  empty: string[]
  chosen: string[]
  onChange: (value: string[]) => void
  onOpen: (open: boolean) => void
}) {
  const [open, setOpen] = useState(false)
  // The chips left out of the row, how many of them are chosen, and whether
  // a scrolled row hides chips before or after those in view.
  const [fit, setFit] = useState({ out: '', uncounted: 0, before: false, after: false })
  const root = useRef<HTMLDivElement>(null)
  const rail = useRef<HTMLDivElement>(null)
  const opener = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const held = choices(chosen)
  const rest = offers(offered, chosen, browsing)
  const key = [...held.map((c) => c.key), '', ...rest].join('|')

  useLayoutEffect(() => {
    const el = rail.current!
    // A changed row is read from its start, where the chosen chips are.
    el.scrollLeft = 0
    // Lays the chips out by their widths, which do not depend on where the
    // row puts them. The row's children are the chosen chips, the chip that
    // counts those left out, then the offered ones.
    const measure = () => {
      const style = getComputedStyle(el)
      const gap = parseFloat(style.columnGap)
      const width = el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
      const w = (i: number) => Math.ceil(el.children[i].getBoundingClientRect().width)
      const out: string[] = []
      let uncounted = 0
      if (style.flexWrap !== 'nowrap') {
        const count = w(held.length)
        let x = 0
        // A chosen chip is shown if the count of those after it still fits.
        let shown = 0
        while (shown < held.length) {
          const last = shown === held.length - 1
          if (x + w(shown) + (last ? 0 : gap + count) > width) break
          x += w(shown) + gap
          shown += 1
        }
        uncounted = held.length - shown
        out.push(...held.slice(shown).map((c) => c.key))
        rest.forEach((id, i) => {
          const wide = w(held.length + 1 + i)
          if (uncounted || x + wide > width) out.push(id)
          else x += wide + gap
        })
      }
      const next = {
        out: out.join('|'),
        uncounted,
        before: el.scrollLeft > 1,
        after: el.scrollWidth - el.clientWidth - el.scrollLeft > 1,
      }
      setFit((f) =>
        f.out === next.out && f.uncounted === next.uncounted && f.before === next.before && f.after === next.after
          ? f
          : next,
      )
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    el.addEventListener('scroll', measure, { passive: true })
    // The chips are wider or narrower once the page's font has loaded.
    let mounted = true
    document.fonts.ready.then(() => mounted && measure())
    return () => {
      mounted = false
      observer.disconnect()
      el.removeEventListener('scroll', measure)
    }
    // held and rest change only as key does.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  useEffect(() => {
    onOpen(open)
    if (!open) return
    const el = list.current!
    const room = () => window.innerHeight - el.getBoundingClientRect().top - LIST_MARGIN
    // The list scrolls within what is left of the window below it.
    const size = () => {
      el.style.maxHeight = `${Math.max(room(), 0)}px`
    }
    // Where the whole list does not fit, the page scrolls to make room for
    // it, at most until the row is just under the pinned controls.
    const pinned = document.querySelector<HTMLElement>('.controls')!.offsetHeight
    const short = Math.min(el.scrollHeight - room(), root.current!.getBoundingClientRect().top - pinned)
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (short > 0) window.scrollBy({ top: short, behavior: still ? 'auto' : 'smooth' })
    size()
    const outside = (e: PointerEvent) => {
      if (!root.current!.contains(e.target as Node)) setOpen(false)
    }
    const escape = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      opener.current!.focus()
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    window.addEventListener('resize', size)
    window.addEventListener('scroll', size, { passive: true })
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
      window.removeEventListener('resize', size)
      window.removeEventListener('scroll', size)
    }
  }, [open, onOpen])

  const drop = (ids: string[]) => onChange(chosen.filter((d) => !ids.includes(d)))
  const toggle = (id: string) => (chosen.includes(id) ? drop([id]) : onChange([...chosen, id]))
  const out = fit.out.split('|')
  const cross = (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  )
  return (
    <div className="disciplines" ref={root}>
      <div className={`rail${fit.before ? ' before' : ''}${fit.after ? ' after' : ''}`} ref={rail} role="group" aria-label="Disciplines">
        {held.map((c) => (
          <button
            key={c.key}
            className={c.area ? 'chip on whole-area' : 'chip on'}
            title={c.area ? c.ids.map((d) => DISCIPLINE.get(d)!.label).join(', ') : undefined}
            aria-pressed
            inert={out.includes(c.key)}
            onClick={() => drop(c.ids)}
          >
            {c.label}
            {cross}
          </button>
        ))}
        <button
          className="chip on count"
          inert={!fit.uncounted}
          aria-label={`${fit.uncounted} more chosen. Show all disciplines`}
          onClick={() => setOpen(!open)}
        >
          +{fit.uncounted}
        </button>
        {rest.map((id) => (
          <button key={id} className="chip" aria-pressed={false} inert={out.includes(id)} onClick={() => toggle(id)}>
            {DISCIPLINE.get(id)!.label}
          </button>
        ))}
      </div>
      <button
        className={open ? 'all open' : 'all'}
        ref={opener}
        aria-expanded={open}
        aria-controls="all-disciplines"
        aria-label="All disciplines"
        onClick={() => setOpen(!open)}
      >
        More
        <svg viewBox="4.75 7.75 14.5 8.5" aria-hidden="true">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && (
        <div className="list" id="all-disciplines" ref={list} role="group" aria-label="All disciplines">
          <p className="hint">
            Choose disciplines or whole areas. Results match any of them.
            {chosen.length > 0 && (
              <button className="reset" onClick={() => onChange([])}>
                Clear
              </button>
            )}
          </p>
          {AREAS.map((area) => {
            const ids = MEMBERS.get(area)!
            const n = ids.filter((d) => chosen.includes(d)).length
            const state = n === ids.length ? 'all' : n ? 'some' : 'none'
            return (
              <div key={area} className="area" role="group" aria-label={area}>
                <h2>
                  {/* Chooses the whole area, or drops it when it is all chosen. */}
                  <button
                    className={`whole ${state}`}
                    role="checkbox"
                    aria-checked={state === 'all' ? true : state === 'some' ? 'mixed' : false}
                    onClick={() => (state === 'all' ? drop(ids) : onChange([...chosen, ...ids.filter((d) => !chosen.includes(d))]))}
                  >
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <rect x="1" y="1" width="14" height="14" rx="4" />
                      {state !== 'none' && <path d={state === 'all' ? 'M4.5 8.2l2.4 2.4 4.6-5' : 'M4.75 8h6.5'} />}
                    </svg>
                    {area}
                  </button>
                </h2>
                <div className="chips">
                  {ids.map((id) => {
                    const on = chosen.includes(id)
                    const none = !on && empty.includes(id)
                    return (
                      <button
                        key={id}
                        className={`chip${on ? ' on' : ''}${none ? ' none' : ''}`}
                        title={none ? 'No results' : undefined}
                        aria-pressed={on}
                        onClick={() => toggle(id)}
                      >
                        {DISCIPLINE.get(id)!.label}
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
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

// A source tag, as "Expo 2026". It is a link to the search filtered to its
// source and its year alone, or with both dropped if the search is filtered
// to just that already; on the search page a plain click changes the filters
// in place, keeping the query and disciplines. The source is the filter the
// tag's own source falls under: a Symposium tag filters to Expo projects, as
// the source filter groups them. An AY URG tag falls under none, and is not
// a link.
function Tag({ look, source, year, name }: { look: string; source: Source | ''; year: number; name: string }) {
  const filter = useContext(Filter)
  const on = source !== '' && (filter?.tagged(source, year) ?? false)
  const label = `${name} ${year}`
  // The year dropdowns can't show a year outside theirs, so readUrl drops it.
  if (!source || !YEARS.includes(year)) return <span className={`tag ${look}`}>{label}</span>
  return (
    <a
      href={filter ? filter.tagHref(source, year) : `/?source=${source}&from=${year}&to=${year}`}
      className={`tag ${look}${on ? ' on' : ''}`}
      title={on ? `Stop filtering by ${label}` : `Filter by ${label}`}
      onClick={(e) => {
        if (!filter || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
        e.preventDefault()
        filter.tagToggle(source, year)
      }}
    >
      {label}
    </a>
  )
}

function Result({
  project,
  place: where,
  open = false,
}: {
  project: Project
  place: Omit<Place, 'project'>
  open?: boolean
}) {
  const place = { project: project.id, ...where }
  const filter = useContext(Filter)
  const filedUnder = project.disciplines.filter((d) => DISCIPLINE.has(d))
  // A click on any of the result's links, also one that opens it in a new
  // tab (a middle click is an auxclick).
  function clicked(e: React.MouseEvent) {
    const a = (e.target as Element).closest<HTMLElement>('a[data-link]')
    if (a && (e.type === 'click' || e.button === 1)) {
      report('click', place, { link: a.dataset.link, record: a.dataset.record })
    }
  }
  const grants = project.records.filter((r) => r.kind === 'grant')
  const theses = project.records.filter((r) => r.kind === 'thesis')
  const papers = project.records.filter((r) => r.kind === 'paper')
  const fellowships = project.records.filter((r) => r.kind === 'fellowship')
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
  const topShared = top.every((x) => sameSet(x.advisors, top[0]?.advisors ?? [])) ? (top[0]?.advisors ?? []) : null
  // A faculty member's project that Leopold Fellows assisted on is theirs,
  // not the fellows': it is named as such, and the fellows follow year by year.
  const faculty = [...new Set(fellowships.flatMap((r) => r.advisors ?? []))]
  const facultyLine = `Faculty project of ${list(faculty)}, assisted by Leopold Fellows`
  // What the faculty wrote in offering the project, each text once.
  const offered: Section[] = []
  for (const r of fellowships)
    if (r.abstract && !offered.some((s) => sameAbstract(s.abstract, r.abstract!)))
      offered.push({ key: r.id, year: r.year, source: r.source, title: null, students: [], abstract: r.abstract, abstractSource: null, records: [r] })
  // The pages listing the fellows: the current year's, and the earlier years'.
  const lists = [...new Map(fellowships.map((r) => [r.url, r])).values()].map((r) =>
    sourceLink(r.id, r.source, r.url, r.url.includes('previous') ? 'Previous Leopold Fellows' : `Leopold Fellows ${academicYear(r)}`),
  )
  const years = [...new Map(parts.map((s) => [`${s.source} ${s.year}`, s])).values()]
  const multiple = parts.length + written.length > 1
  // Every listing gets its own link, also where its abstract is shown merged
  // with another's; a year's listings are told apart by their pages.
  const listed = new Map<number, number>()
  for (const e of expo) listed.set(e.year, (listed.get(e.year) ?? 0) + 1)

  // The links to a section's sources: each listing's page in its program, a
  // thesis's paper, report or list, a paper's PDF and post. Brief, they don't
  // name the section's source and year (see below for when). A thesis the
  // MMSS library catalogues twice links the library once.
  function sources(s: Section, brief: boolean): SourceLink[] {
    const label = (name: string, what: string, own = true) =>
      brief && own ? what[0].toUpperCase() + what.slice(1) : `${name} ${what}`
    const links = [
      // Each listing's poster, where Prowl hosts it, then its program page.
      ...(s.entries ?? []).flatMap((e) => {
        const what = `listing${listed.get(e.year)! > 1 && e.page ? `, p. ${e.page}` : ''}`
        const own = e.source === s.source && e.year === s.year
        const name = `${SOURCE_NAMES[e.source]} ${e.year}`
        return [
          ...(e.pdf ? [sourceLink(e.id, 'expo-pdf', e.pdf.url, label(name, PDF_NAMES[e.pdf.kind], own), true)] : []),
          sourceLink(e.id, e.source, e.url, label(name, what, own), true),
        ]
      }),
      // A record's PDF that Prowl hosts comes first, then where it is from.
      ...(s.records ?? []).flatMap((r) =>
        !r.pdf
          ? []
          : r.kind === 'thesis'
            ? [sourceLink(r.id, 'thesis-pdf', r.pdf, brief ? 'Thesis' : `Thesis ${r.year}`, true)]
            : [sourceLink(r.id, 'nurj-pdf', r.pdf, label(`NURJ ${r.year}`, 'paper'), true)],
      ),
      ...(s.records ?? []).map((r) =>
        r.kind === 'thesis' ? thesisLink(r) : sourceLink(r.id, r.source, r.url, label(`NURJ ${r.year}`, paperLink(r))),
      ),
    ]
    return links.filter((l, i) => links.findIndex((m) => m.href === l.href && m.label === l.label) === i)
  }
  // Where a section's abstract is from, when not from its own source.
  const credit = (s: Section) =>
    s.abstractSource ? [sourceLink(s.key, 'abstract', s.abstractSource.url, `Abstract: ${s.abstractSource.name}`)] : []

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

  // The sections the card shows under its title. A thesis or paper with
  // nothing of its own to show, neither title, people nor abstract, has none.
  const all = [
    ...parts.map((s) => ({
      section: s,
      heading:
        s.title !== project.title
          ? `${SOURCE_NAMES[s.source]} ${s.year}: ${s.title ?? 'untitled'}`
          : years.length > 1 || written.length
            ? `${SOURCE_NAMES[s.source]} ${s.year}`
            : null,
      who: people(s.students),
    })),
    ...written.map((w) => ({
      section: w,
      heading: !sameTitle(w.title, project.title) ? `${w.label}: ${w.title}` : multiple ? w.label! : null,
      who: people(w.students),
    })),
  ]
  const shown = all.filter((x) => x.section.entries || x.heading || x.who || x.section.abstract)
  // With several sections, each one's links sit under it, and a grant's under
  // the card's byline: the title and byline are the grant's, which has no
  // section. A thesis or paper not shown has none either, so its links come
  // after the last section. With one section or none, all the links do.
  //
  // A link to a record's own document names the record's source and year
  // ("NURJ 2015 post") only where its row has to: when the row holds links of
  // more than one record, or sits apart from its record's section. A row
  // under its own section, or the one row of a card with one record, leaves
  // them out ("Post", "Thesis"). A link to a page listing many records, a
  // grant's winners or a thesis's list, always names it ("SURG 2015 winners").
  const apart = shown.length > 1
  const rest = all.filter((x) => !apart || !shown.includes(x)).map((x) => x.section)
  const winners = grants.map((g) => sourceLink(g.id, g.source, g.url, `${SOURCE_NAMES[g.source]} ${g.year} winners`))
  const one = !apart && grants.length + rest.length === 1
  const below = [...(apart ? [] : winners), ...rest.flatMap((s) => sources(s, one)), ...rest.flatMap(credit), ...lists]

  return (
    <article className="result" onClick={clicked} onAuxClick={clicked}>
      <ShareButton project={project} place={place} />
      <div className="tags">
        {grants.map((g) => (
          <Tag key={g.id} look="surg" source={g.source === 'surg' ? 'surg' : ''} year={g.year} name={SOURCE_NAMES[g.source]} />
        ))}
        {years.map((s) => (
          <Tag key={`${s.source} ${s.year}`} look="expo" source="expo" year={s.year} name={SOURCE_NAMES[s.source]} />
        ))}
        {/* One tag a year, also for a thesis two departments list: the
            source links name the department. */}
        {[...new Set(theses.map((t) => t.year))].map((year) => (
          <Tag key={year} look="thesis" source="theses" year={year} name="Thesis" />
        ))}
        {papers.map((x) => (
          <Tag key={x.id} look="nurj" source="nurj" year={x.year} name="NURJ" />
        ))}
        {/* One tag for all a project's fellowships, which can run to
            fifteen years: the academic years they span. */}
        {fellowships.length > 0 && (
          <span className="tag leopold">
            Leopold {fellowships[0].year}–{String(fellowships.at(-1)!.year + 1).slice(2)}
          </span>
        )}
        {/* The disciplines the project is filed under. Each is a link to
            the search with it chosen, or dropped if it is chosen already;
            on the search page a plain click changes the filter in place. */}
        {filedUnder.length > 0 && (
          <span className="filed">
            {filedUnder.map((d) => {
              const { label } = DISCIPLINE.get(d)!
              const on = filter?.chosen.includes(d) ?? false
              return (
                <span key={d}>
                  <a
                    href={filter ? filter.href(d) : `/?discipline=${d}`}
                    className={on ? 'on' : undefined}
                    title={on ? `Stop filtering by ${label}` : `Filter by ${label}`}
                    onClick={(e) => {
                      if (!filter || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
                      e.preventDefault()
                      filter.toggle(d)
                    }}
                  >
                    {label}
                  </a>
                </span>
              )
            })}
          </span>
        )}
      </div>
      <h2>
        <a href={`/p/${project.share}`} data-link="page">
          {project.title ? <Marked text={project.title} /> : <span className="untitled">{untitled(project)}</span>}
        </a>
      </h2>
      <p className="people">
        <Marked text={top.length ? byline(top) : facultyLine} />
      </p>
      {apart && <Links links={winners} />}
      {shown.map(({ section, heading, who }) => (
        <Abstract
          key={section.key}
          section={section}
          heading={heading}
          people={who}
          links={apart ? [...sources(section, true), ...credit(section)] : []}
          place={place}
          open={open}
        />
      ))}
      {fellowships.length > 0 && (
        <Fellows fellowships={fellowships} title={project.title} heading={top.length ? facultyLine : null} open={open} />
      )}
      {offered.map((section) => (
        <Abstract
          key={section.key}
          section={section}
          heading={`The project as offered to applicants, ${academicYear(section.records![0])}`}
          people={null}
          links={
            section.records![0].offered
              ? [
                  sourceLink(
                    section.key,
                    'leopold-offered',
                    section.records![0].offered,
                    `Faculty projects ${academicYear(section.records![0])} (archived)`,
                  ),
                ]
              : []
          }
          place={place}
          open={open}
        />
      ))}
      <Links links={below} />
    </article>
  )
}

// A fellowship's academic year, as "2019–20".
const academicYear = (r: ProjectRecord) => r.academic_year!.replace('-', '–')

// The rows a result shows of a project's fellowships before "Show earlier years".
const FELLOW_ROWS = 3

// A faculty project's Leopold Fellows, year by year, newest first, as the
// title is the latest year's. A year whose entry titles or describes the
// project otherwise than the result's title (see nearTitle) says how: a
// project is retitled as it grows, and one year's fellows may work on one
// part of it. A result
// shows the latest FELLOW_ROWS rows until asked for the rest; a project's
// own page, and a result whose quoted phrase is in a later row, shows all.
function Fellows({
  fellowships,
  title,
  heading,
  open,
}: {
  fellowships: ProjectRecord[]
  title: string | null
  heading: string | null
  open: boolean
}) {
  const quotes = useContext(Quotes)
  const [all, setAll] = useState(open)
  const rows: { key: string; when: string; fellows: string[]; as: string | null; on: string | null }[] = []
  const named = (r: ProjectRecord) => r.title ?? r.description ?? null
  // A year some of whose entries name the project otherwise says what each
  // of its entries names it, also the one that names it as the result does.
  const varied = new Set(fellowships.filter((r) => named(r) !== null && !nearTitle(named(r)!, title)).map((r) => r.year))
  for (const r of [...fellowships].sort((a, b) => b.year - a.year || (a.id < b.id ? -1 : 1))) {
    const name = varied.has(r.year) ? named(r) : null
    let row = rows.find((x) => x.when === academicYear(r) && nearTitle(x.as ?? x.on, name))
    if (!row) {
      row = { key: r.id, when: academicYear(r), fellows: [], as: name && r.title, on: name && !r.title ? name : null }
      rows.push(row)
    }
    row.fellows = [...new Set([...row.fellows, ...(r.students ?? [])])]
  }
  const hidden = rows.slice(FELLOW_ROWS)
  const found =
    quotes !== null &&
    hidden.some((x) => [...x.fellows, x.as ?? '', x.on ?? ''].some((t) => new RegExp(quotes.source, 'iu').test(t)))
  const shown = all || found ? rows : rows.slice(0, FELLOW_ROWS)
  return (
    <section className="fellows">
      {heading && (
        <h3>
          <Marked text={heading} />
        </h3>
      )}
      <ul>
        {shown.map((x) => (
          <li key={x.key}>
            <span className="when">{x.when}</span>
            <span>
              <Marked text={list(x.fellows)} />
              {x.as && (
                <span className="as">
                  , as “<Marked text={x.as} />”
                </span>
              )}
              {x.on && (
                <span className="as">
                  , on <Marked text={x.on} />
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
      {shown.length < rows.length && (
        <button aria-expanded="false" onClick={() => setAll(true)}>
          Show earlier years
        </button>
      )}
    </section>
  )
}

// Where a NURJ paper's link goes, as its label says after "NURJ" and the
// year: its post on thenurj.com, Scribd, or the Wayback Machine's capture of
// the Issuu volume it was printed in.
function paperLink(x: ProjectRecord) {
  const host = new URL(x.url).hostname
  if (host === 'web.archive.org') return 'on Issuu (archived)'
  if (host.endsWith('scribd.com')) return 'on Scribd'
  return 'post'
}

// The MMSS thesis library's front page, behind a Northwestern login.
const MMSS_LIBRARY = 'https://nuwildcat.sharepoint.com/sites/WNB-MMSS-Library/Thesis%20Library%20Public/'

// A thesis's source: its technical report, its department's list of honors
// theses, or the MMSS library. The library is linked at its front page, also
// for a thesis whose paper Prowl hosts (the library's copy of which is the
// same file), and says so where it has only the catalog entry.
function thesisLink(t: ProjectRecord): SourceLink {
  if (t.report) return sourceLink(t.id, t.source, t.url, 'Technical report', t.url.endsWith('.pdf'))
  if (department(t) === 'MMSS')
    return sourceLink(t.id, t.source, MMSS_LIBRARY, t.pdf ? 'MMSS thesis library' : 'MMSS thesis library (paper unavailable)')
  const [from, to] = t.academic_year!.split('-')
  return sourceLink(t.id, t.source, t.url, `${t.department} honors theses, ${from}–${to.slice(2)}`, t.url.endsWith('.pdf'))
}

// Whether two titles are one however they are capitalized or punctuated.
function sameTitle(a: string | null, b: string | null) {
  const key = (t: string | null) => (t?.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []).join(' ')
  return key(a) === key(b)
}

// Whether two titles of a project are one but for an article or an ending:
// "A History of Laughter" and "The History of Laughter", "Small Business
// in Poor Urban Communities" and "Small Businesses in...".
function nearTitle(a: string | null, b: string | null) {
  const words = (t: string | null) =>
    (t?.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []).filter((w) => !['a', 'an', 'the'].includes(w))
  const [x, y] = [words(a), words(b)]
  return (
    x.length === y.length &&
    x.every((w, i) => (w.startsWith(y[i]) || y[i].startsWith(w)) && Math.abs(w.length - y[i].length) <= 2)
  )
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
      records: theses,
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
      records: [x],
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
  entries?: ExpoEntry[] // a poster's listings
  records?: ProjectRecord[] // a thesis's records, or a paper's one
}
// A link to one of a project's sources, as the query log knows it (link and
// record) and as the card words it.
type SourceLink = { record: string; link: string; href: string; label: string; pdf: boolean }

// What a listing's hosted PDF is called on the card.
const PDF_NAMES = { poster: 'poster', slides: 'slides', document: 'PDF' }

function sourceLink(record: string, link: string, href: string, label: string, pdf = false): SourceLink {
  return { record, link, href, label, pdf }
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
        entries: [],
      }
      byAbstract.set(e.abstract, s)
    }
    s.entries!.push(e)
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
function ShareButton({ project, place }: { project: Project; place: Place }) {
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
    report('share', place)
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
  links,
  place,
  open: initiallyOpen,
}: {
  section: Section
  heading: string | null
  people: string | null
  links: SourceLink[]
  place: Place
  open: boolean
}) {
  const [open, setOpen] = useState(initiallyOpen)
  // Whether the abstract runs past the clamp, so that it has more to show.
  const [overflows, setOverflows] = useState(false)
  const text = useRef<HTMLParagraphElement>(null)
  const body = useRef<HTMLSpanElement>(null)
  const more = useRef<HTMLButtonElement>(null)
  const quotes = useContext(Quotes)
  // Counts the abstract's lines, from its inline text's line boxes, and
  // counts again when the card's width changes.
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
    <section
      className="abstract"
      onClick={(e) => {
        const button = more.current
        const target = e.target as Element
        if (!button || button.contains(target) || target.closest('a')) return
        if (!getSelection()?.isCollapsed) return
        const r = button.getBoundingClientRect()
        if (
          Math.abs(e.clientX - (r.left + r.right) / 2) <= r.width / 2 + MORE_REACH_X &&
          Math.abs(e.clientY - (r.top + r.bottom) / 2) <= r.height / 2 + MORE_REACH_Y
        )
          button.click()
      }}
    >
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
          </p>
          {!open && overflows && (
            <button
              ref={more}
              className="more"
              aria-expanded="false"
              onClick={() => {
                report('expand', place, { record: section.key })
                setOpen(true)
              }}
            >
              Show more
            </button>
          )}
        </div>
      )}
      <Links links={links} />
    </section>
  )
}

// A row of links to sources, each opening in a new tab.
function Links({ links }: { links: SourceLink[] }) {
  if (!links.length) return null
  return (
    <div className="links">
      {links.map((l) => (
        <a
          key={`${l.record} ${l.link}`}
          href={l.href}
          target="_blank"
          rel="noreferrer"
          data-link={l.link}
          data-record={l.record}
        >
          {l.label} {l.pdf && <PdfIcon />} <ExternalIcon />
        </a>
      ))}
    </div>
  )
}
