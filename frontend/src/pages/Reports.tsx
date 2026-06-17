import { useEffect, useState } from 'react';
import { getReport, listReports, type ValidationReport } from '../api/reports';
import { ReportViewer } from '../components/reports/ReportViewer';
import { DataTable } from '../components/tables/DataTable';

export function Reports() {
  const [reports, setReports] = useState<ValidationReport[]>([]);
  const [content, setContent] = useState('');

  useEffect(() => {
    void listReports().then(setReports).catch(() => setReports([]));
  }, []);

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold text-ink">Validation Reports</h1>
      <DataTable
        rows={reports}
        emptyLabel="No validation reports"
        columns={[
          { header: 'Report', render: (row) => <button className="text-action" onClick={async () => setContent((await getReport(row.report_name)).content)}>{row.report_name}</button> },
          { header: 'Exists', render: (row) => row.exists ? 'Yes' : 'No' },
          { header: 'Path', render: (row) => row.path }
        ]}
      />
      {content && <ReportViewer content={content} />}
    </div>
  );
}
