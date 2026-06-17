import { EmptyState } from './EmptyState';
import type { ReactNode } from 'react';

type Column<T> = { header: string; render: (row: T) => ReactNode };
type Props<T> = { rows: T[]; columns: Column<T>[]; emptyLabel: string; onRowClick?: (row: T) => void };

export function DataTable<T>({ rows, columns, emptyLabel, onRowClick }: Props<T>) {
  if (!rows.length) return <EmptyState label={emptyLabel} />;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="min-w-full divide-y divide-slate-800 bg-panel text-sm">
        <thead className="bg-panelSoft text-left text-xs uppercase text-muted">
          <tr>{columns.map((column) => <th key={column.header} className="px-3 py-3 font-medium">{column.header}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row, index) => (
            <tr key={index} className={`hover:bg-slate-900/60 ${onRowClick ? 'cursor-pointer' : ''}`} onClick={() => onRowClick?.(row)}>
              {columns.map((column) => <td key={column.header} className="px-3 py-3 text-slate-200">{column.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
