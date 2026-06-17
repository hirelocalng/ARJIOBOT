import { NAV_ITEMS, type PageName } from '../../utils/constants';

type Props = { active: PageName; onNavigate: (page: PageName) => void };

export function Sidebar({ active, onNavigate }: Props) {
  return (
    <aside className="fixed inset-x-0 top-0 z-40 border-b border-slate-800 bg-slate-950/95 px-3 py-3 backdrop-blur lg:static lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r lg:px-4 lg:py-5">
      <div className="mb-3 lg:mb-7">
        <div className="text-lg font-semibold text-ink">ArjioBot</div>
        <div className="text-xs text-muted">Private VPS Console</div>
      </div>
      <nav className="flex gap-2 overflow-x-auto pb-1 lg:grid lg:gap-1 lg:overflow-visible lg:pb-0">
        {NAV_ITEMS.map((item) => (
          <button
            key={item}
            onClick={() => onNavigate(item)}
            className={`min-h-11 shrink-0 rounded-md px-3 py-2 text-left text-sm lg:w-full ${active === item ? 'bg-action/15 text-action' : 'text-slate-300 hover:bg-slate-900'}`}
          >
            {item}
          </button>
        ))}
      </nav>
    </aside>
  );
}
