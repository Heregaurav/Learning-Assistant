import type { CSSProperties, ReactNode } from "react";

type SkeletonProps = {
  className?: string;
  width?: CSSProperties["width"];
  height?: CSSProperties["height"];
  radius?: CSSProperties["borderRadius"];
};

export function Skeleton({ className = "", width, height, radius }: SkeletonProps) {
  return (
    <span
      aria-hidden="true"
      className={`skeleton ${className}`}
      style={{ width, height, borderRadius: radius }}
    />
  );
}

export function SkeletonText({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <span className={`skeleton-text ${className}`} aria-hidden="true">
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} className="skeleton-text-line" width={index === lines - 1 ? "68%" : "100%"} />
      ))}
    </span>
  );
}

export function SkeletonAvatar({ size = 44 }: { size?: number }) {
  return <Skeleton className="skeleton-avatar" width={size} height={size} radius="50%" />;
}

export function SkeletonButton({ width = 104 }: { width?: number }) {
  return <Skeleton className="skeleton-button" width={width} height={38} radius={8} />;
}

export function SkeletonCard({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <div className={`skeleton-card ${className}`}>{children ?? <SkeletonText lines={3} />}</div>;
}

export function SkeletonList({ count = 3, className = "" }: { count?: number; className?: string }) {
  return (
    <div className={`skeleton-list ${className}`} aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <div className="skeleton-list-row" key={index}>
          <SkeletonAvatar size={34} />
          <div className="skeleton-list-copy">
            <Skeleton height={12} width="42%" />
            <Skeleton height={10} width={index % 2 ? "74%" : "88%"} />
          </div>
          <SkeletonButton width={66} />
        </div>
      ))}
    </div>
  );
}

export function SkeletonLesson() {
  return (
    <section className="skeleton-lesson" aria-hidden="true">
      <Skeleton width="34%" height={11} />
      <Skeleton className="skeleton-lesson-title" width="64%" height={34} />
      <div className="skeleton-lesson-chips"><Skeleton width={82} height={24} radius={999} /><Skeleton width={112} height={24} radius={999} /></div>
      <Skeleton className="skeleton-lesson-lead" width="82%" height={15} />
      <div className="skeleton-lesson-tabs"><Skeleton width="94%" height={38} /></div>
      <div className="skeleton-lesson-section">
        <Skeleton width="38%" height={20} />
        <SkeletonText lines={4} />
        <Skeleton className="skeleton-lesson-content-card" height={110} />
        <Skeleton width="28%" height={18} />
        <SkeletonText lines={3} />
      </div>
      <div className="skeleton-lesson-interaction"><Skeleton width="32%" height={15} /><Skeleton height={72} /><SkeletonButton /></div>
    </section>
  );
}

export function SkeletonProfile() {
  return (
    <section className="skeleton-page" aria-hidden="true">
      <div className="skeleton-profile-heading"><SkeletonAvatar size={76} /><div><Skeleton width={120} height={11} /><Skeleton width={245} height={29} /><Skeleton width={190} height={12} /></div></div>
      <div className="skeleton-stat-grid">{Array.from({ length: 4 }, (_, i) => <SkeletonCard key={i} className="skeleton-stat"><Skeleton width="52%" height={11} /><Skeleton width="30%" height={27} /></SkeletonCard>)}</div>
      <div className="skeleton-two-column">{Array.from({ length: 2 }, (_, i) => <SkeletonCard key={i}><Skeleton width="45%" height={16} /><SkeletonList count={3} /></SkeletonCard>)}</div>
      <SkeletonCard><Skeleton width="35%" height={16} /><SkeletonList count={2} /></SkeletonCard>
    </section>
  );
}

export function SkeletonClassroom() {
  return (
    <section className="skeleton-classroom" aria-hidden="true">
      <Skeleton width={100} height={12} />
      <header className="skeleton-classroom-header"><div className="skeleton-classroom-title"><Skeleton width={210} height={11} /><Skeleton width="58%" height={33} /><Skeleton width="78%" height={13} /></div><div className="skeleton-classroom-actions"><SkeletonButton /><SkeletonButton width={128} /></div></header>
      <div className="skeleton-tabs"><Skeleton width="100%" height={42} /></div>
      <div className="skeleton-classroom-layout"><div className="skeleton-outline"><Skeleton width="54%" height={15} /><SkeletonList count={5} /></div><div className="skeleton-classroom-main"><Skeleton width="42%" height={24} /><SkeletonText lines={2} /><SkeletonCard><Skeleton width="45%" height={17} /><SkeletonList count={2} /></SkeletonCard><SkeletonCard><Skeleton width="60%" height={17} /><SkeletonList count={2} /></SkeletonCard></div></div>
    </section>
  );
}

export function SkeletonGraph() {
  return (
    <div className="skeleton-graph" aria-hidden="true">
      <div className="skeleton-graph-orbit"><Skeleton width={74} height={74} radius="50%" /><Skeleton width={48} height={48} radius="50%" /><Skeleton width={56} height={56} radius="50%" /><Skeleton width={38} height={38} radius="50%" /></div>
      <Skeleton width={190} height={11} />
    </div>
  );
}

export function SkeletonDashboard() {
  return <SkeletonProfile />;
}
