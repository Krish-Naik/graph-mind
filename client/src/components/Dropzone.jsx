import { useDropzone } from 'react-dropzone';

const ACCEPT = {
  'text/csv': ['.csv'], 'text/tab-separated-values': ['.tsv'], 'text/plain': ['.txt'],
  'application/vnd.ms-excel': ['.csv', '.xls'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/zip': ['.zip'], 'application/x-zip-compressed': ['.zip'],
};

/** Drag-and-drop OR click-to-browse. */
export default function Dropzone({ onFiles, compact = false, hint }) {
  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({ onDrop: onFiles, accept: ACCEPT, multiple: true });
  return (
    <div>
      <div {...getRootProps({ className: `dropzone ${isDragActive ? 'active' : ''}`, style: compact ? { padding: 18 } : undefined })}>
        <input {...getInputProps()} />
        {isDragActive ? <p><strong>Drop the files here...</strong></p> : (
          <>
            <p style={{ margin: 0, fontSize: compact ? 14 : 16 }}>
              <strong>Drag &amp; drop</strong> CSV / TSV / Excel / <strong>ZIP</strong> files here, or <strong>click to browse</strong>
            </p>
            <p className="muted" style={{ margin: '6px 0 0' }}>{hint || 'A single CSV is enough for most data. Have several related tables? Upload them together, or just drop one ZIP.'}</p>
          </>
        )}
      </div>
      {fileRejections.length > 0 && (
        <div className="alert err" style={{ marginTop: 8 }}>
          Unsupported: {fileRejections.map((r) => r.file.name).join(', ')}. Use CSV, TSV, TXT, XLSX, XLS or ZIP.
        </div>
      )}
    </div>
  );
}
