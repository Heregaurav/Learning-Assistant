import { useEffect, useRef, useState } from "react";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { Pause, Play, Sun } from "lucide-react";
import Learn from "./pages/Learn";
import History from "./pages/History";
import Session from "./pages/Session";
import Profile from "./pages/Profile";
import Landing from "./pages/Landing";
import { Boundary } from "./components/States";
import { getProfile, googleAuth } from "./lib/api";

type User = {
  id: string;
  name: string;
  email: string;
  picture: string;
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
  onSignedIn: (user: User, token: string) => void;
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
            onSignedIn(result.user, result.token);
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
  const [plainBackground, setPlainBackground] = useState(false);
  const [videoPaused, setVideoPaused] = useState(false);
  const [pictureFailed, setPictureFailed] = useState(false);
  const backgroundVideoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    setPictureFailed(false);
  }, [user?.picture]);
  useEffect(() => {
    if (!localStorage.getItem("google_credential")) {
      const guestId = localStorage.getItem(GUEST_ID_KEY);
      if (guestId) {
        setUser({
          id: guestId,
          name: "Guest",
          email: "",
          picture: "",
          isGuest: true,
        });
      }
      setChecking(false);
      return;
    }
    getProfile()
      .then((profile) =>
        setUser({
          id: profile.id,
          name: profile.name,
          email: profile.email,
          picture: profile.picture,
          isGuest: false,
        }),
      )
      .catch(() => {
        localStorage.removeItem("google_credential");
        setUser(null);
      })
      .finally(() => setChecking(false));
  }, []);
  const signIn = (next: User, token: string) => {
    localStorage.removeItem(GUEST_ID_KEY);
    localStorage.setItem("google_credential", token);
    setUser(next);
  };
  const useGuest = () => {
    setUser({
      id: getGuestId(),
      name: "Guest",
      email: "",
      picture: "",
      isGuest: true,
    });
  };
  const signOut = () => {
    localStorage.removeItem("google_credential");
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
            <nav aria-label="Main">
              <NavLink to="/" end>
                Learn
              </NavLink>
              <NavLink to="/history">History</NavLink>
              <NavLink to="/profile">Profile</NavLink>
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
          </header>
          <main>
            <Boundary>
              <Routes>
                <Route path="/" element={<Learn />} />
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
