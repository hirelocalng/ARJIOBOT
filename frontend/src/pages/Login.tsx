import { useState } from 'react';
import { login } from '../api/auth';

export function Login({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('Enter dashboard password');

  async function submit() {
    try {
      setStatus('Checking login...');
      await login(password);
      setPassword('');
      onAuthenticated();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Login failed');
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-8 text-slate-100">
      <div className="w-full max-w-sm rounded-lg border border-slate-800 bg-panel p-5">
        <div className="mb-4">
          <h1 className="text-xl font-semibold text-ink">ArjioBot</h1>
          <p className="mt-1 text-sm text-muted">Private VPS control dashboard</p>
        </div>
        <label className="grid gap-2 text-sm">
          <span className="text-muted">Dashboard Password</span>
          <input
            className="min-h-12 rounded-md border border-slate-700 bg-slate-950 px-3 text-slate-100 outline-none focus:border-action"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') void submit(); }}
            autoComplete="current-password"
          />
        </label>
        <button className="mt-4 min-h-12 w-full rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" onClick={() => void submit()}>
          Log In
        </button>
        <div className="mt-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-muted">{status}</div>
      </div>
    </div>
  );
}
