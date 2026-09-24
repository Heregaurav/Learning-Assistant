import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getSessions } from '../lib/api'
import { EmptyState, ErrorState, LoadingState } from '../components/States'

export default function History() {
  const [rows, setRows] = useState<any[] | null>(null), [err, setErr] = useState(''), [q, setQ] = useState('')
  const load = () => { setErr(''); setRows(null); getSessions().then(setRows).catch(e => setErr(e.message)) }
  useEffect(load, [])
  if (err) return <ErrorState message={err} onRetry={load} />
  if (!rows) return <LoadingState />
  const shown = rows.filter(r => r.topic.toLowerCase().includes(q.toLowerCase()))
  return (
    <>
      <header className="hero intro"><h1>Study history</h1>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search topics" aria-label="Search topics" /></header>
      {rows.length === 0 ? <EmptyState title="No study sessions yet." hint="Start learning to build your history." />
        : <div className="list">{shown.map(r => (
          <Link key={r.id} to={`/session/${r.id}`} className="row link">
            <span><b>{r.topic}</b><small>{new Date(r.createdAt).toLocaleDateString()} · {r.difficulty}</small></span>
            <span className="score-pill">{r.evaluation?.completed ? `${r.evaluation.score}%` : 'Not finished'}</span>
          </Link>))}</div>}
    </>)
}
