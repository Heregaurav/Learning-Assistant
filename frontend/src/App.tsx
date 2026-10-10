import { useCallback, useEffect, useRef, useState } from "react";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { Menu, Pause, Play, Sun, X } from "lucide-react";
import Learn from "./pages/Learn";
import History from "./pages/History";
import Session from "./pages/Session";
import Profile from "./pages/Profile";
import Landing from "./pages/Landing";
import ClassroomsPage from "./pages/Classrooms";
import ClassroomDetail from "./pages/ClassroomDetail";
import AdminUsers from "./pages/AdminUsers";
import { Boundary } from "./components/States";
import { getAuthSession, googleAuth, logout } from "./lib/api";
import type { Role } from "./types";

type User = {
  id: string;
  name: string;
  email: string;
  picture: string;
  role?: Role;
  isGuest?: boolean;
};

const GUEST_ID_KEY = "curiosity.guest-id";
const getGuestId = () => {
  const existing = localStorage.getItem(GUEST_ID_KEY);
  if (existing) return existing;
  const id = `guest_${crypto.randomUUID()}`;
  localStorage.setItem(GUEST_ID_KEY, id);
  return id;
};

const prismaBackgroundVideo =
  "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260405_170732_8a9ccda6-5cff-4628-b164-059c500a2b41.mp4";

declare global {
  interface Window {
    google?: any;
  }
}

function GoogleSignIn({
  onSignedIn,
}: {
  onSignedIn: (user: User) => void;
}) {
  const [error, setError] = useState("");
  useEffect(() => {
    const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
    if (!clientId) {
      setError("Set VITE_GOOGLE_CLIENT_ID in frontend/.env.");
      return;
    }
    let cancelled = false;
    let retryTimer: number | undefined;
    const render = () => {
      if (cancelled || !window.google?.accounts?.id) return false;
      const target = document.getElementById("google-signin");
      if (!target) return false;
      target.replaceChildren();
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: async (response: { credential?: string }) => {
          if (!response.credential) {
            setError(
              "Google did not return an identity token. Please try again.",
            );
            return;
          }
          try {
            const result = await googleAuth(response.credential);
            onSignedIn(result.user);
          } catch (e) {
            setError((e as Error).message);
          }
        },
      });
      window.google.accounts.id.renderButton(target, {
        theme: "outline",
        size: "large",
        width: 280,
      });
      return true;
    };
    const attemptRender = () => {
      if (!render() && !cancelled)
        retryTimer = window.setTimeout(attemptRender, 100);
    };
    attemptRender();
    window.addEventListener("google-loaded", attemptRender);
    return () => {
      cancelled = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      window.removeEventListener("google-loaded", attemptRender);
    };
  }, [onSignedIn]);
  return (
    <div className="landing-google-auth">
      <div id="google-signin" />
      {error && <p className="err">{error}</p>}
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [showSignIn, setShowSignIn] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [plainBackground, setPlainBackground] = useState(false);
  const [videoPaused, setVideoPaused] = useState(false);
  const [pictureFailed, setPictureFailed] = useState(false);
  const backgroundVideoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    setPictureFailed(false);
  }, [user?.picture]);
  useEffect(() => {
    getAuthSession()
      .then((session) => {
        if (session.authenticated && session.user) {
          setUser({ ...session.user, isGuest: false });
          return;
        }
        const guestId = localStorage.getItem(GUEST_ID_KEY);
        if (guestId) {
          setUser({
            id: guestId,
            name: "Guest",
            email: "",
            picture: "",
            isGuest: true,
          });
        } else {
          setUser(null);
        }
      })
      .catch(() => {
        const guestId = localStorage.getItem(GUEST_ID_KEY);
        setUser(guestId ? { id: guestId, name: "Guest", email: "", picture: "", isGuest: true } : null);
      })
      .finally(() => setChecking(false));
  }, []);
  const signIn = useCallback((next: User) => {
    localStorage.removeItem(GUEST_ID_KEY);
    setUser(next);
  }, []);
  const useGuest = () => {
    setUser({
      id: getGuestId(),
      name: "Guest",
      email: "",
      picture: "",
      role: "STUDENT",
      isGuest: true,
    });
  };
  const signOut = () => {
    void logout().catch(() => undefined);
    localStorage.removeItem(GUEST_ID_KEY);
    localStorage.removeItem("curiosity.active-lesson");
    setUser(null);
  };
  const toggleVideo = () => {
    const video = backgroundVideoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play();
      setVideoPaused(false);
    } else {
      video.pause();
      setVideoPaused(true);
    }
  };
  if (checking)
    return (
      <div className="state">
        <p>Checking your sign-in…</p>
      </div>
    );
  if (!user)
    return (
      <Landing
        onStart={() => setShowSignIn(true)}
        onGuest={useGuest}
        googleSignIn={showSignIn ? <GoogleSignIn onSignedIn={signIn} /> : null}
      />
    );
  return (
    <BrowserRouter>
      <div className={`prisma-auth-shell${plainBackground ? " is-plain" : ""}`}>
        <video
          ref={backgroundVideoRef}
          className="prisma-auth-video"
          src={prismaBackgroundVideo}
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
          aria-hidden="true"
        />
        <div className="noise-overlay prisma-auth-noise" aria-hidden="true" />
        <div className="prisma-auth-gradient" aria-hidden="true" />
        <div className="prisma-auth-content">
          <header className="top">
            <a className="logo" href="/" aria-label="Curiosity home">
              <img src="/curiosity2.jpg" alt="Curiosity" />
              <span>curiosity</span>
            </a>
            <button
              type="button"
              className="mobile-menu-toggle"
              onClick={() => setMobileMenuOpen((open) => !open)}
              aria-label={mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
              aria-expanded={mobileMenuOpen}
              aria-controls="main-mobile-menu"
            >
              {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
            <div
              id="main-mobile-menu"
              className={`mobile-menu${mobileMenuOpen ? " is-open" : ""}`}
            >
              <nav aria-label="Main">
                <NavLink to="/" end onClick={() => setMobileMenuOpen(false)}>
                  Learn
                </NavLink>
                <NavLink to="/classrooms" onClick={() => setMobileMenuOpen(false)}>
                  Classrooms
                </NavLink>
                {user.role === "ADMIN" && (
                  <NavLink to="/admin/users" onClick={() => setMobileMenuOpen(false)}>
                    Admin
                  </NavLink>
                )}
                <NavLink to="/history" onClick={() => setMobileMenuOpen(false)}>
                  History
                </NavLink>
                <NavLink to="/profile" onClick={() => setMobileMenuOpen(false)}>
                  Profile
                </NavLink>
              </nav>
              <div className="nav-actions">
              <div
                className="background-controls"
                aria-label="Background controls"
              >
                <button
                  className="background-control"
                  onClick={() => setPlainBackground(!plainBackground)}
                  title={
                    plainBackground
                      ? "Use cinematic background"
                      : "Use simple background"
                  }
                  aria-label={
                    plainBackground
                      ? "Use cinematic background"
                      : "Use simple black and cream background"
                  }
                >
                  <Sun size={15} />
                  <span className="background-control-label">
                    {plainBackground ? "Cinematic" : "Plain"}
                  </span>
                </button>
                <button
                  className="background-control"
                  onClick={toggleVideo}
                  title={
                    videoPaused
                      ? "Play background video"
                      : "Pause background video"
                  }
                  aria-label={
                    videoPaused
                      ? "Play background video"
                      : "Pause background video"
                  }
                >
                  <span className="background-control-icon">
                    {videoPaused ? <Play size={15} /> : <Pause size={15} />}
                  </span>
                </button>
              </div>
              <button
                className="profile-button"
                onClick={signOut}
                title={user.isGuest ? "Leave guest mode" : `Signed in as ${user.email}`}
              >
                {user.picture && !pictureFailed ? (
                  <img
                    src={user.picture}
                    alt=""
                    referrerPolicy="no-referrer"
                    onError={() => setPictureFailed(true)}
                  />
                ) : (
                  user.picture && <span className="profile-button-fallback" aria-hidden="true">{user.name.charAt(0).toUpperCase()}</span>
                )}
                <span>{user.isGuest ? "Guest mode" : user.name}</span>
                <small>{user.isGuest ? "Login for more" : "Sign out"}</small>
              </button>
              </div>
            </div>
          </header>
          <main>
            <Boundary>
              <Routes>
                <Route path="/" element={<Learn />} />
                <Route
                  path="/classrooms"
                  element={
                    <ClassroomsPage
                      user={user}
                      onRequireSignIn={() => {
                        localStorage.removeItem(GUEST_ID_KEY);
                        setUser(null);
                        setShowSignIn(true);
                      }}
                    />
                  }
                />
                <Route path="/classrooms/:classroomId" element={<ClassroomDetail user={user} />} />
                {user.role === "ADMIN" && <Route path="/admin/users" element={<AdminUsers currentUserId={user.id} />} />}
                <Route path="/history" element={<History />} />
                <Route path="/session/:id" element={<Session />} />
                <Route path="/profile" element={<Profile />} />
              </Routes>
            </Boundary>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}
