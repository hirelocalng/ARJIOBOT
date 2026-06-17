export function ReportViewer({ content }: { content: string }) {
  return <iframe title="Validation report" className="h-[640px] w-full rounded-lg border border-slate-800 bg-white" srcDoc={content} />;
}
