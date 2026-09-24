import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import Learn from './pages/Learn'
import History from './pages/History'
import Session from './pages/Session'
import Profile from './pages/Profile'
import Landing from './pages/Landing'
import { Boundary } from './components/States'
import { getProfile, googleAuth } from './lib/api'

type User = { id: string; name: string; email: string; picture: string }

const prismaBackgroundVideo = 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260405_170732_8a9ccda6-5cff-4628-b164-059c500a2b41.mp4'

declare global { interface Window { google?: any } }

function GoogleSignIn({ onSignedIn }: { onSignedIn: (user: User, token: string) => void }) {
  const [error, setError] = useState('')
  useEffect(() => {
    const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
    if (!clientId) { setError('Set VITE_GOOGLE_CLIENT_ID in frontend/.env.'); return }
    let cancelled = false
    let retryTimer: number | undefined
    const render = () => {
      if (cancelled || !window.google?.accounts?.id) return false
      const target = document.getElementById('google-signin')
      if (!target) return false
      target.replaceChildren()
      window.google.accounts.id.initialize({ client_id: clientId, callback: async (response: { credential?: string }) => {
        if (!response.credential) { setError('Google did not return an identity token. Please try again.'); return }
        try { const result = await googleAuth(response.credential); onSignedIn(result.user, result.token) }
        catch (e) { setError((e as Error).message) }
      } })
      window.google.accounts.id.renderButton(target, { theme: 'outline', size: 'large', width: 280 })
      return true
    }
    const attemptRender = () => {
      if (!render() && !cancelled) retryTimer = window.setTimeout(attemptRender, 100)
    }
    attemptRender()
    window.addEventListener('google-loaded', attemptRender)
    return () => {
      cancelled = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      window.removeEventListener('google-loaded', attemptRender)
    }
  }, [onSignedIn])
  return <div className="landing-google-auth"><div id="google-signin" />{error && <p className="err">{error}</p>}</div>
}

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(true)
  const [showSignIn, setShowSignIn] = useState(false)
  useEffect(() => {
    if (!localStorage.getItem('google_credential')) { setChecking(false); return }
    getProfile().then(profile => setUser({ id: profile.id, name: profile.name, email: profile.email, picture: profile.picture })).catch(() => { localStorage.removeItem('google_credential'); setUser(null) }).finally(() => setChecking(false))
  }, [])
  const signIn = (next: User, token: string) => { localStorage.setItem('google_credential', token); setUser(next) }
  const signOut = () => { localStorage.removeItem('google_credential'); setUser(null) }
  if (checking) return <div className="state"><p>Checking your sign-in…</p></div>
  if (!user) return <Landing onStart={() => setShowSignIn(true)} googleSignIn={showSignIn ? <GoogleSignIn onSignedIn={signIn} /> : null} />
  return (
    <BrowserRouter>
      <div className="prisma-auth-shell">
        <video className="prisma-auth-video" src={prismaBackgroundVideo} autoPlay loop muted playsInline preload="auto" aria-hidden="true" />
        <div className="noise-overlay prisma-auth-noise" aria-hidden="true" />
        <div className="prisma-auth-gradient" aria-hidden="true" />
        <div className="prisma-auth-content">
          <header className="top"><b className="logo">Learning Assistant</b>
            <nav aria-label="Main"><NavLink to="/" end>Learn</NavLink><NavLink to="/history">History</NavLink><NavLink to="/profile">Profile</NavLink></nav>
            <button className="profile-button" onClick={signOut} title={`Signed in as ${user.email}`}>
              {user.picture && <img src={user.picture} alt="" />}<span>{user.name}</span><small>Sign out</small>
            </button></header>
          <main><Boundary><Routes>
            <Route path="/" element={<Learn />} /><Route path="/history" element={<History />} />
            <Route path="/session/:id" element={<Session />} /><Route path="/profile" element={<Profile />} />
          </Routes></Boundary></main>
        </div>
      </div>
    </BrowserRouter>)
}
