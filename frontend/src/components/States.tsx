import { Component, ReactNode } from "react";
export const LoadingState = () => (
  <div className="state" role="status" aria-live="polite">
    <h2>Preparing your lesson…</h2>
    <p>
      Reading your input, then writing the explanation, flashcards and quiz.
      This can take up to a minute.
    </p>
    <div className="bar">
      <i />
    </div>
  </div>
);
export const ErrorState = ({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) => (
  <div className="state err" role="alert">
    <h2>{message}</h2>
    {onRetry && (
      <button className="btn" onClick={onRetry}>
        Try again
      </button>
    )}
  </div>
);
export const EmptyState = ({
  title,
  hint,
}: {
  title: string;
  hint?: string;
}) => (
  <div className="state">
    <h2>{title}</h2>
    {hint && <p>{hint}</p>}
  </div>
);
export class Boundary extends Component<
  { children: ReactNode },
  { bad: boolean }
> {
  state = { bad: false };
  static getDerivedStateFromError() {
    return { bad: true };
  }
  render() {
    return this.state.bad ? (
      <ErrorState
        message="Something went wrong."
        onRetry={() => this.setState({ bad: false })}
      />
    ) : (
      this.props.children
    );
  }
}
