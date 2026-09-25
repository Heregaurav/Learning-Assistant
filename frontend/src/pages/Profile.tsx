import { useEffect, useState } from "react";
import { getProfile } from "../lib/api";
import { ErrorState, LoadingState } from "../components/States";

type ProfileData = {
  name: string;
  email: string;
  picture?: string;
  stats: {
    topicsStudied: number;
    sessionsCompleted: number;
    averageScore: number;
    cardsReviewed: number;
    quizzesCompleted: number;
  };
  strong: { name: string; progress: { score: number } }[];
  needsReview: { name: string; progress: { score: number } }[];
};

export default function Profile() {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [pictureFailed, setPictureFailed] = useState(false);
  const [error, setError] = useState("");
  const load = () => {
    setError("");
    getProfile()
      .then(setProfile)
      .catch((e) => setError(e.message));
  };
  useEffect(load, []);
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!profile) return <LoadingState />;
  return (
    <>
      <header className="hero intro profile-hero">
        <div
          className="profile-photo"
          aria-label={`${profile.name}'s Google profile picture`}
        >
          {profile.picture && !pictureFailed ? (
            <img
              src={profile.picture}
              alt=""
              referrerPolicy="no-referrer"
              onError={() => setPictureFailed(true)}
            />
          ) : (
            <span>{profile.name.charAt(0).toUpperCase()}</span>
          )}
        </div>
        <p className="eyebrow">YOUR PROFILE</p>
        <h1>{profile.name}</h1>
        <p className="lead">{profile.email}</p>
      </header>
      <section className="grid2 profile-stats">
        <section className="panel">
          <h3>Topics studied</h3>
          <strong>{profile.stats.topicsStudied}</strong>
        </section>
        <section className="panel">
          <h3>Sessions completed</h3>
          <strong>{profile.stats.sessionsCompleted}</strong>
        </section>
        <section className="panel">
          <h3>Average score</h3>
          <strong>{profile.stats.averageScore}%</strong>
        </section>
        <section className="panel">
          <h3>Cards reviewed</h3>
          <strong>{profile.stats.cardsReviewed}</strong>
        </section>
      </section>
      <div className="grid2 profile-topics">
        <section className="profile-topic-panel">
          <div className="profile-topic-heading">
            <div>
              <p className="eyebrow">PERFORMING WELL</p>
              <h2>Strong topics</h2>
            </div>
            <span className="topic-count">{profile.strong.length}</span>
          </div>
          {profile.strong.length ? (
            profile.strong.map((topic) => (
              <p className="row" key={topic.name}>
                <span className="topic-name">{topic.name}</span>
                <span className="score-pill">{topic.progress.score}%</span>
              </p>
            ))
          ) : (
            <p className="topic-empty">Complete a quiz to build your strengths.</p>
          )}
        </section>
        <section className="profile-topic-panel">
          <div className="profile-topic-heading">
            <div>
              <p className="eyebrow">KEEP PRACTICING</p>
              <h2>Needs review</h2>
            </div>
            <span className="topic-count">{profile.needsReview.length}</span>
          </div>
          {profile.needsReview.length ? (
            profile.needsReview.map((topic) => (
              <p className="row" key={topic.name}>
                <span className="topic-name">{topic.name}</span>
                <span className="score-pill">{topic.progress.score}%</span>
              </p>
            ))
          ) : (
            <p className="topic-empty">No review topics yet.</p>
          )}
        </section>
      </div>
    </>
  );
}
