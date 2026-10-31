import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getPlatformUsers, updatePlatformUserRole } from "../lib/api";
import type { PlatformUser } from "../lib/api";
import { SkeletonList } from "../components/Skeletons";

type Props = { currentUserId: string };

export default function AdminUsers({ currentUserId }: Props) {
  const [users, setUsers] = useState<PlatformUser[]>([]);
  const [roles, setRoles] = useState<Record<string, PlatformUser["role"]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const list = await getPlatformUsers();
      setUsers(list);
      setRoles(Object.fromEntries(list.map((user) => [user.id, user.role])));
    } catch (reason) {
      setError((reason as Error).message || "Unable to load users.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const saveRole = async (user: PlatformUser) => {
    setError("");
    setNotice("");
    try {
      await updatePlatformUserRole(user.id, roles[user.id]);
      setNotice(`Role updated for ${user.email || user.name}.`);
      await refresh();
    } catch (reason) {
      setError((reason as Error).message || "Unable to update role.");
    }
  };

  return (
    <section className="mx-auto max-w-6xl px-4 py-8 text-[#E1E0CC]">
      <p className="text-xs uppercase tracking-[0.18em] text-primary/75">Platform administration</p>
      <h1 className="mt-2 text-3xl font-semibold">Users and roles</h1>
      <p className="mt-2 max-w-2xl text-sm text-[#D7D1B5]">New accounts start as students. Assign faculty access here; classroom permissions are enforced by the API.</p>
      <div className="mt-4 rounded-xl border border-primary/20 bg-primary/5 p-4 text-xs text-[#D7D1B5] flex flex-wrap items-center justify-between gap-3">
        <span>Looking to manage students and teachers for a specific course? Classroom user and role administration is now located directly inside each classroom&apos;s <strong>People</strong> tab.</span>
        <Link to="/classrooms" className="rounded-lg bg-primary/20 px-3 py-1.5 font-medium text-primary hover:bg-primary hover:text-black transition-colors">Go to Classrooms</Link>
      </div>
      {error && <p role="alert" className="mt-4 rounded-lg border border-red-400/40 bg-red-950/40 p-3 text-sm text-red-100">{error}</p>}
      {notice && <p role="status" className="mt-4 text-sm text-emerald-200">{notice}</p>}
      {loading ? <div aria-busy="true" aria-label="Loading users"><p className="sr-only" role="status">Loading users…</p><SkeletonList count={5} /></div> : users.length === 0 ? (
        <p className="py-8 text-sm text-primary/70">No registered users yet.</p>
      ) : (
        <div className="mt-6 divide-y divide-primary/15 border-y border-primary/20">
          {users.map((user) => (
            <article key={user.id} className="grid gap-3 py-4 md:grid-cols-[1fr_180px_auto] md:items-center">
              <div>
                <h2 className="font-medium">{user.name}</h2>
                <p className="text-sm text-primary/70">{user.email || "No email"}{user.id === currentUserId ? " · You" : ""}</p>
              </div>
              <select
                aria-label={`Role for ${user.email || user.name}`}
                value={roles[user.id] ?? user.role}
                disabled={user.id === currentUserId}
                onChange={(event) => setRoles((current) => ({ ...current, [user.id]: event.target.value as PlatformUser["role"] }))}
                className="rounded-lg border border-primary/25 bg-black/40 px-3 py-2 text-sm disabled:opacity-50"
              >
                <option value="STUDENT">Student</option>
                <option value="FACULTY">Faculty</option>
                <option value="ADMIN">Admin</option>
              </select>
              <button
                disabled={user.id === currentUserId || roles[user.id] === user.role}
                onClick={() => void saveRole(user)}
                className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-black disabled:cursor-not-allowed disabled:opacity-40"
              >Save role</button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
