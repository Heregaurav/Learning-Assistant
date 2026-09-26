import { Component, ReactNode } from "react";
import { AlertCircle, RefreshCw, X } from "lucide-react";
export const LoadingState = ({ stage = "understanding" }: { stage?: string }) => {
  const copy: Record<string, string> = {
    uploading: "Uploading document…",
    reading: "Reading your document and extracting the text…",
    understanding: "Understanding the material and identifying the key ideas…",
    building: "Building explanations, study blocks, flashcards and quiz…",
    creating_cards: "Creating flashcards from the document…",
    preparing_quiz: "Preparing your quiz…",
    almost_ready: "Almost ready…",
    ready: "Your lesson is ready.",
  };
  return (
    <div className="state" role="status" aria-live="polite">
      <h2>Preparing your lesson…</h2>
      <p>{copy[stage] ?? copy.understanding} This can take up to a minute.</p>
      <div className="bar">
        <i />
      </div>
    </div>
  );
};
export const ErrorState = ({
  message,
  title = "Unable to complete request",
  description,
  onRetry,
  onDismiss,
}: {
  message: string;
  title?: string;
  description?: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}) => (
  <section className="state error-alert" role="alert" aria-live="assertive">
    <span className="error-alert-icon" aria-hidden="true">
      <AlertCircle size={19} />
    </span>
    <div className="error-alert-copy">
      <h2>{title}</h2>
      <p>{description ?? message}</p>
    </div>
    {onRetry && (
      <button className="error-alert-retry" onClick={onRetry}>
        <RefreshCw size={14} aria-hidden="true" /> Try again
      </button>
    )}
    {onDismiss && (
      <button
        className="error-alert-dismiss"
        onClick={onDismiss}
        aria-label="Dismiss error"
        title="Dismiss"
      >
        <X size={16} aria-hidden="true" />
      </button>
    )}
  </section>
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
