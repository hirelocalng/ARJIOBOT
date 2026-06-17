import type { ReactNode } from 'react';
import type { BotStatus } from '../../types/common';
import type { ExchangeAccount } from '../../types/accounts';
import type { PageName } from '../../utils/constants';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

type Props = { active: PageName; status: BotStatus | null; defaultAccount?: ExchangeAccount; onNavigate: (page: PageName) => void; children: ReactNode };

export function Layout({ active, status, defaultAccount, onNavigate, children }: Props) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="flex min-h-screen">
        <Sidebar active={active} onNavigate={onNavigate} />
        <main className="min-w-0 flex-1 pt-32 lg:pt-0">
          <Topbar status={status} defaultAccount={defaultAccount} />
          <section className="px-3 py-4 sm:p-6">{children}</section>
        </main>
      </div>
    </div>
  );
}
