import { useEffect, useRef, useState } from "react";
import apiService from "./services";
import { SavedAnswer, SavedAnswerContent } from "./types";
import { styles } from "./styles";

interface Props {
  retain: boolean;
  onRetain: (value: boolean) => void;
}

export default function RetainedAnswers({ retain, onRetain }: Props) {
  const [policy, setPolicy] = useState<{ enabled: boolean; retention_days: number }>();
  const [items, setItems] = useState<SavedAnswer[]>([]);
  const [content, setContent] = useState<SavedAnswerContent>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef(new AbortController());

  useEffect(() => {
    const current = new AbortController();
    controller.current = current;
    apiService.answerRetentionPolicy(current.signal).then(setPolicy).catch((reason: unknown) => {
      if (!current.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load retention policy.");
    });
    return () => current.abort();
  }, [controller]);

  const run = async (action: () => Promise<void>) => {
    setContent(undefined);
    setError("");
    setBusy(true);
    try {
      await action();
    } catch (reason) {
      if (!controller.current.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "Saved answer is unavailable.");
      }
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  };

  return (
    <section style={styles.card} aria-label="Saved answers">
      <h2 style={styles.sectionTitle}>Saved answers</h2>
      <label>
        <input type="checkbox" checked={retain} disabled={!policy?.enabled}
          onChange={(event) => onRetain(event.target.checked)} />
        Save future answers privately for up to {policy?.retention_days ?? 30} days
      </label>
      <p>Saving is optional. Only you can read saved answers with current access.
        Access or index changes redact the entire saved question and answer.
        Clearing the chat does not delete saved answers.</p>
      {!policy?.enabled && <p>Saving requires operator-configured private storage and local FAISS retrieval.</p>}
      <button type="button" disabled={busy || !policy?.enabled}
        onClick={() => run(async () => setItems(await apiService.listSavedAnswers(controller.current.signal)))}>
        Refresh saved answers
      </button>
      {error && <p role="alert">{error}</p>}
      {items.map((item) => (
        <div key={item.id}>
          <span>{new Date(item.created_at * 1000).toLocaleString()} - {item.status}</span>{" "}
          <button type="button" disabled={busy || item.status !== "available"}
            onClick={() => run(async () => setContent(await apiService.readSavedAnswer(item.id, controller.current.signal)))}>
            Open
          </button>{" "}
          <button type="button" disabled={busy} onClick={() => run(async () => {
            await apiService.deleteSavedAnswer(item.id, controller.current.signal);
            setItems((current) => current.filter((entry) => entry.id !== item.id));
          })}>Delete</button>
        </div>
      ))}
      {content && <article>
        <p><strong>Question:</strong> {content.question}</p>
        <p style={{ whiteSpace: "pre-wrap" }}>{content.answer}</p>
        <p>Expires: {new Date(content.expires_at * 1000).toLocaleString()}</p>
        <button type="button" onClick={() => setContent(undefined)}>Close</button>
      </article>}
    </section>
  );
}
