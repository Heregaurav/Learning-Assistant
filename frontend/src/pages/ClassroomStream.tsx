import { FormEvent, useEffect, useState } from "react";
import { createClassroomPost, getClassroomStream, replyToClassroomPost } from "../lib/api";
import type { ClassroomPost } from "../lib/api";

type Props = { classroomId: string; canAnnounce: boolean };

export default function ClassroomStream({ classroomId, canAnnounce }: Props) {
  const [posts, setPosts] = useState<ClassroomPost[]>([]);
  const [kind, setKind] = useState<"announcement" | "discussion">(canAnnounce ? "announcement" : "discussion");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [replies, setReplies] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = async () => {
    setLoading(true);
    try {
      setPosts(await getClassroomStream(classroomId));
      setError("");
    } catch (reason) {
      setError((reason as Error).message || "Unable to load the classroom stream.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, [classroomId]);

  const publish = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await createClassroomPost(classroomId, { kind, title: title.trim(), body: body.trim() });
      setTitle("");
      setBody("");
      setNotice("Post published.");
      await refresh();
    } catch (reason) {
      setError((reason as Error).message || "Unable to publish post.");
    }
  };

  const reply = async (postId: string) => {
    const text = replies[postId]?.trim();
    if (!text) return;
    try {
      await replyToClassroomPost(classroomId, postId, text);
      setReplies((current) => ({ ...current, [postId]: "" }));
      setNotice("Reply added.");
      await refresh();
    } catch (reason) {
      setError((reason as Error).message || "Unable to add reply.");
    }
  };

  return (
    <section className="mt-12 border-t border-primary/20 pt-7">
      <p className="text-xs uppercase tracking-[0.18em] text-primary/70">Classroom community</p>
      <h2 className="mt-1 text-xl font-semibold">Stream</h2>
      {error && <p role="alert" className="mt-4 rounded-lg border border-red-400/40 bg-red-950/40 p-3 text-sm text-red-100">{error}</p>}
      {notice && <p role="status" className="mt-3 text-sm text-emerald-200">{notice}</p>}
      <form onSubmit={publish} className="mt-4 grid gap-3 border-b border-primary/20 pb-5">
        <div className="flex gap-2">
          <select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)} className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm">
            {canAnnounce && <option value="announcement">Announcement</option>}
            <option value="discussion">Discussion</option>
          </select>
          <input required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Post title" className="w-full rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
        </div>
        <textarea required value={body} onChange={(event) => setBody(event.target.value)} placeholder="Share an update or ask a question" className="min-h-20 rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
        <button className="justify-self-start rounded-lg bg-primary px-4 py-2 text-sm font-medium text-black">Post to stream</button>
      </form>
      {loading ? <p className="py-5 text-sm text-primary/70">Loading posts…</p> : posts.length === 0 ? (
        <p className="py-5 text-sm text-primary/70">No posts yet. Start the classroom conversation.</p>
      ) : (
        <div className="divide-y divide-primary/15">
          {posts.map((post) => (
            <article key={post.id} className="py-5">
              <p className="text-[10px] uppercase tracking-[0.16em] text-primary/65">{post.kind} · {post.authorId}</p>
              <h3 className="mt-1 font-medium">{post.title}</h3>
              <p className="mt-2 whitespace-pre-wrap text-sm text-[#D7D1B5]">{post.body}</p>
              <div className="mt-4 grid gap-2 border-l border-primary/20 pl-3">
                {post.replies.map((item) => <p key={item.id} className="text-sm text-[#D7D1B5]"><span className="text-xs text-primary/65">{item.authorId}: </span>{item.body}</p>)}
                <div className="flex gap-2">
                  <input value={replies[post.id] ?? ""} onChange={(event) => setReplies((current) => ({ ...current, [post.id]: event.target.value }))} placeholder="Reply" className="w-full rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm" />
                  <button onClick={() => void reply(post.id)} disabled={!replies[post.id]?.trim()} className="rounded-lg border border-primary/30 px-3 py-2 text-xs text-primary disabled:opacity-40">Reply</button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
