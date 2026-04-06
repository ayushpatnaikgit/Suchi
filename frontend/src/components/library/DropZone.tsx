import { useState, useCallback } from "react";
import { Upload } from "lucide-react";

interface DropZoneProps {
  onDrop: (files: File[]) => Promise<void>;
  children: React.ReactNode;
}

/** Check if a drag event is an external file drop (not an internal entry drag) */
function isExternalFileDrag(e: React.DragEvent): boolean {
  // Internal entry drags use our custom MIME type
  if (e.dataTransfer.types.includes("application/cloudref-entry-id")) {
    return false;
  }
  // External file drops have "Files" in the type list
  return e.dataTransfer.types.includes("Files");
}

export function DropZone({ onDrop, children }: DropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    if (!isExternalFileDrag(e)) return; // Ignore internal drags
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    if (!isExternalFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget === e.target) {
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      if (!isExternalFileDrag(e)) return; // Ignore internal drags
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      const files = Array.from(e.dataTransfer.files).filter((f) =>
        f.name.toLowerCase().endsWith(".pdf")
      );

      if (files.length === 0) {
        setUploadStatus("Only PDF files are supported");
        setTimeout(() => setUploadStatus(null), 3000);
        return;
      }

      setIsUploading(true);
      setUploadStatus(`Processing ${files.length} PDF${files.length > 1 ? "s" : ""}...`);

      try {
        await onDrop(files);
        setUploadStatus(
          `Added ${files.length} reference${files.length > 1 ? "s" : ""}`
        );
        setTimeout(() => setUploadStatus(null), 3000);
      } catch (err) {
        setUploadStatus(
          err instanceof Error ? err.message : "Upload failed"
        );
        setTimeout(() => setUploadStatus(null), 5000);
      } finally {
        setIsUploading(false);
      }
    },
    [onDrop]
  );

  return (
    <div
      className="relative flex-1 flex flex-col min-h-0"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {children}

      {/* Drag overlay — only for external file drops */}
      {isDragging && (
        <div className="absolute inset-0 z-50 bg-blue-50/90 dark:bg-blue-950/90 border-2 border-dashed border-blue-400 dark:border-blue-500 rounded-lg flex flex-col items-center justify-center backdrop-blur-sm">
          <Upload size={48} className="text-blue-500 mb-3" />
          <div className="text-lg font-medium text-blue-700">
            Drop PDF files here
          </div>
          <div className="text-sm text-blue-500 mt-1">
            Metadata will be extracted automatically
          </div>
        </div>
      )}

      {/* Upload status toast */}
      {uploadStatus && (
        <div
          className={`absolute bottom-4 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg shadow-lg text-sm font-medium ${
            isUploading
              ? "bg-blue-600 text-white"
              : uploadStatus.startsWith("Added")
              ? "bg-green-600 text-white"
              : "bg-red-600 text-white"
          }`}
        >
          {isUploading && (
            <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2 align-middle" />
          )}
          {uploadStatus}
        </div>
      )}
    </div>
  );
}
