const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
export class ApiError extends Error { constructor(public code: string, message: string) { super(message) } }
export const MSG: Record<string, string> = {
  auth_required: 'Sign in with Google to continue.',
  invalid_auth: 'Google rejected this sign-in token. Check the OAuth client ID and authorized origin.',
  auth_expired: 'Your Google sign-in has expired. Please sign in again.',
  auth_not_configured: 'Google sign-in is not configured on the backend.',
  invalid_json: 'AI returned invalid JSON. Please try again.',
  bad_schema: 'The generated learning material had an unexpected format. Please try again.',
  empty: 'No learning material was generated. Please try again.',
  timeout: 'This is taking longer than expected. Retry?',
  llm_failed: "We couldn't generate your lesson.",
  network: 'Unable to connect to the server.',
  database_unavailable: 'The database is unavailable right now.',
  database_auth_failed: 'MongoDB rejected the username or password. Check backend/.env.',
  missing_api_key: 'Add the selected provider API key to backend/.env.',
}

async function req<T>(path: string, init: RequestInit = {}, timeoutMs = 70000): Promise<T> {
  const ctl = new AbortController(), t = setTimeout(() => ctl.abort('timeout'), timeoutMs)
  init.signal?.addEventListener('abort', () => ctl.abort('cancelled'))
  try {
    const token = localStorage.getItem('google_credential')
    const r = await fetch(BASE + path, { ...init, signal: ctl.signal, headers: {
      'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}),
    } })
    if (!r.ok) {
      const b = await r.json().catch(() => ({}))
      const code = b?.detail?.code ?? `http_${r.status}`
      throw new ApiError(code, MSG[code] ?? b?.detail?.message ?? 'Request failed.')
    }
    return (await r.json()) as T
  } catch (e) {
    if (e instanceof ApiError) throw e
    if ((e as Error).name === 'AbortError') throw new ApiError(ctl.signal.reason === 'timeout' ? 'timeout' : 'cancelled', MSG.timeout)
    throw new ApiError('network', MSG.network)
  } finally { clearTimeout(t) }
}

export const googleAuth = (credential: string) =>
  req<{ user: { id: string; name: string; email: string; picture: string }; token: string }>(
    '/api/auth/google', { method: 'POST', body: JSON.stringify({ credential }) })
  export const getProfile = () => req<any>('/api/profile')

export const learn = (content: string, difficulty: string, provider: string, model: string, signal: AbortSignal) =>
  req<{ sessionId: string; topic: string; learningContent: unknown }>('/api/learn',
    { method: 'POST', body: JSON.stringify({ content, difficulty, provider, model }), signal })
export const completeSession = (id: string, body: object) =>
  req<{ topicProgress: number }>(`/api/sessions/${id}/complete`, { method: 'POST', body: JSON.stringify(body) })
export const getSessions = () => req<any[]>('/api/sessions')
export const getSession = (id: string) => req<any>(`/api/sessions/${id}`)
