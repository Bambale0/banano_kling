'use client'

import { useCallback, useRef, useState } from 'react'
import type { UploadedFile } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Upload, X, Loader2, Image as ImageIcon, Video } from 'lucide-react'

interface UploadAreaProps {
  files: UploadedFile[]
  onFilesChange: (files: UploadedFile[]) => void
  maxFiles: number
  accept: string
  required?: boolean
  onUpload?: (file: File) => Promise<UploadedFile>
}

export function UploadArea({ 
  files, 
  onFilesChange, 
  maxFiles, 
  accept,
  required,
  onUpload,
}: UploadAreaProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const handleFiles = useCallback(async (fileList: FileList) => {
    setUploadError(null)
    let currentFiles = [...files]

    for (const file of Array.from(fileList)) {
      if (currentFiles.length >= maxFiles) break
      if (accept.startsWith('image/') && !file.type.startsWith('image/')) {
        setUploadError('Можно загружать только изображения')
        continue
      }
      if (accept.startsWith('video/') && !file.type.startsWith('video/')) {
        setUploadError('Можно загружать только видео')
        continue
      }

      const pendingFile: UploadedFile = {
        id: `file_${Date.now()}_${Math.random().toString(36).slice(2)}`,
        name: file.name,
        url: file.type.startsWith('image') ? URL.createObjectURL(file) : '',
        type: file.type.startsWith('video') ? 'video' : 'image',
        size: file.size,
        uploading: true,
      }

      currentFiles = [...currentFiles, pendingFile]
      onFilesChange(currentFiles)

      try {
        const uploadedFile = onUpload
          ? await onUpload(file)
          : {
              ...pendingFile,
              url: pendingFile.url || URL.createObjectURL(file),
              uploading: false,
            }
        currentFiles = currentFiles.map((item) =>
          item.id === pendingFile.id ? { ...uploadedFile, id: pendingFile.id } : item
        )
        onFilesChange(currentFiles)
      } catch (error) {
        currentFiles = currentFiles.filter((item) => item.id !== pendingFile.id)
        onFilesChange(currentFiles)
        setUploadError(
          error instanceof Error ? error.message : 'Не удалось загрузить файл'
        )
      }
    }
  }, [files, maxFiles, onFilesChange, onUpload])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    handleFiles(e.dataTransfer.files)
  }, [handleFiles])

  const handleRemove = (id: string) => {
    onFilesChange(files.filter(f => f.id !== id))
  }

  const canUploadMore = files.length < maxFiles

  return (
    <div className="space-y-3">
      {/* Dropzone */}
      {canUploadMore && (
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setIsDragging(true)
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "relative flex flex-col items-center justify-center",
            "p-6 rounded-xl border-2 border-dashed cursor-pointer",
            "transition-all duration-200",
            isDragging 
              ? "border-gold bg-gold/5" 
              : required 
                ? "border-gold/50 bg-gold/5 hover:border-gold hover:bg-gold/10"
                : "border-border/50 bg-secondary/30 hover:border-border hover:bg-secondary/50"
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept={accept}
            multiple={maxFiles > 1}
            onChange={(e) => e.target.files && void handleFiles(e.target.files)}
            className="sr-only"
          />
          
          <div className={cn(
            "w-12 h-12 rounded-xl flex items-center justify-center mb-3",
            required ? "bg-gold/20" : "bg-secondary/80"
          )}>
            <Upload className={cn("w-6 h-6", required ? "text-gold" : "text-muted-foreground")} />
          </div>
          
          <p className="text-sm text-foreground mb-1">
            {isDragging ? 'Отпустите файлы' : 'Нажмите или перетащите'}
          </p>
          <p className="text-xs text-muted-foreground">
            Макс. {maxFiles} {maxFiles === 1 ? 'файл' : 'файла'}
          </p>
        </div>
      )}

      {/* File chips */}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {files.map((file) => (
            <div
              key={file.id}
              className={cn(
                "group relative flex items-center gap-2 pl-2 pr-1 py-1 rounded-lg",
                "bg-secondary/80 border border-border/50",
                "transition-all duration-200 hover:border-border"
              )}
            >
              {/* Preview */}
              <div className="w-8 h-8 rounded overflow-hidden bg-secondary flex-shrink-0">
                {file.uploading ? (
                  <div className="w-full h-full flex items-center justify-center">
                    <Loader2 className="w-4 h-4 text-muted-foreground animate-spin" />
                  </div>
                ) : file.type === 'image' ? (
                  <img src={file.url} alt="" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <Video className="w-4 h-4 text-cyan" />
                  </div>
                )}
              </div>
              
              {/* Name */}
              <span className="text-xs text-foreground max-w-[100px] truncate">
                {file.name}
              </span>
              
              {/* Remove button */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleRemove(file.id)
                }}
                className={cn(
                  "w-6 h-6 rounded flex items-center justify-center",
                  "text-muted-foreground hover:text-foreground hover:bg-secondary",
                  "transition-colors"
                )}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {uploadError && (
        <p className="text-xs text-destructive">{uploadError}</p>
      )}

      <p className="text-xs text-muted-foreground">
        {accept.startsWith('image/')
          ? 'PNG, JPG, WEBP. Удаляйте лишние референсы прямо из списка.'
          : 'MP4, MOV и другие video-файлы. Держите короткие и чистые референсы для лучшего результата.'}
      </p>
    </div>
  )
}
