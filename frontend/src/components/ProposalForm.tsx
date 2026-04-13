import { useState, useEffect, useRef, useImperativeHandle, forwardRef } from 'react'

export interface GenerateRequest {
  surveyNotes: string
  photoKeys: string[]
  documentKeys: string[]
  sopKeys: string[]
  referenceProposalId: string | null
}

export interface ProposalFormHandle {
  reset: () => void
}

interface ProposalFormProps {
  onSubmit: (formData: GenerateRequest) => void
  isLoading: boolean
  disabled: boolean
}

interface PastProposal {
  proposalId: string
  status: string
  createdAt?: string
  approvedAt?: string
}

const ALLOWED_PHOTO_TYPES = ['image/jpeg', 'image/png']
const ALLOWED_DOC_TYPES = [
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]
const ALLOWED_DOC_EXTENSIONS = ['.pdf', '.doc', '.docx']

function isAllowedPhoto(f: File) { return ALLOWED_PHOTO_TYPES.includes(f.type) }
function isAllowedDoc(f: File) {
  if (ALLOWED_DOC_TYPES.includes(f.type)) return true
  return ALLOWED_DOC_EXTENSIONS.some(ext => f.name.toLowerCase().endsWith(ext))
}

async function uploadFile(file: File): Promise<string> {
  const apiUrl = import.meta.env.VITE_API_URL as string
  const res = await fetch(`${apiUrl}/upload-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fileName: file.name, fileType: file.type }),
  })
  if (!res.ok) throw new Error(`Failed to get upload URL for ${file.name}`)
  const { uploadUrl, s3Key } = await res.json()
  const putRes = await fetch(uploadUrl, { method: 'PUT', body: file, headers: { 'Content-Type': file.type } })
  if (!putRes.ok) throw new Error(`Failed to upload ${file.name}`)
  return s3Key as string
}

// Drag-and-drop file upload box
function DropZone({
  id, label, accept, hint, files, error, disabled, inputRef,
  onFiles, onClear,
}: {
  id: string; label: string; accept: string; hint: string
  files: File[]; error: string; disabled: boolean
  inputRef: React.RefObject<HTMLInputElement | null>
  onFiles: (files: File[]) => void
  onClear: () => void
}) {
  const [dragging, setDragging] = useState(false)

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    if (disabled) return
    onFiles(Array.from(e.dataTransfer.files))
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    onFiles(Array.from(e.target.files ?? []))
  }

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1.5">{label}</label>
      <div
        onDragOver={e => { e.preventDefault(); if (!disabled) setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        className={`relative border-2 border-dashed rounded-xl px-4 py-5 text-center cursor-pointer transition-all duration-200 ${
          disabled ? 'opacity-50 cursor-not-allowed bg-gray-50' :
          dragging ? 'border-indigo-400 bg-indigo-50' :
          files.length > 0 ? 'border-indigo-300 bg-indigo-50/40' :
          'border-gray-300 bg-gray-50 hover:border-indigo-400 hover:bg-indigo-50/30'
        }`}
      >
        <input ref={inputRef} id={id} type="file" multiple accept={accept} disabled={disabled} onChange={handleChange} className="hidden" />
        {files.length === 0 ? (
          <div className="flex flex-col items-center gap-1.5">
            <svg className="w-7 h-7 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
            <p className="text-sm text-gray-500">Drop files here or <span className="text-indigo-600 font-medium">browse</span></p>
            <p className="text-xs text-gray-400">{hint}</p>
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {files.map(f => (
              <div key={f.name} className="flex items-center gap-2 text-sm text-indigo-700">
                <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span className="truncate">{f.name}</span>
              </div>
            ))}
            <button
              type="button"
              onClick={e => { e.stopPropagation(); onClear() }}
              className="mt-1 text-xs text-red-500 hover:text-red-700 self-start"
            >
              Clear
            </button>
          </div>
        )}
      </div>
      {error && <p role="alert" className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}

export default forwardRef<ProposalFormHandle, ProposalFormProps>(function ProposalForm(
  { onSubmit, isLoading, disabled },
  ref,
) {
  const [surveyNotes, setSurveyNotes] = useState('')
  const [photos, setPhotos] = useState<File[]>([])
  const [documents, setDocuments] = useState<File[]>([])
  const [sopDocs, setSopDocs] = useState<File[]>([])
  const [referenceProposalId, setReferenceProposalId] = useState('')
  const [pastProposals, setPastProposals] = useState<PastProposal[]>([])
  const [photoError, setPhotoError] = useState('')
  const [docError, setDocError] = useState('')
  const [sopError, setSopError] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [uploadError, setUploadError] = useState('')

  const photoInputRef = useRef<HTMLInputElement>(null)
  const docInputRef   = useRef<HTMLInputElement>(null)
  const sopInputRef   = useRef<HTMLInputElement>(null)

  useImperativeHandle(ref, () => ({
    reset() {
      setSurveyNotes(''); setPhotos([]); setDocuments([]); setSopDocs([])
      setReferenceProposalId(''); setPhotoError(''); setDocError('')
      setSopError(''); setSubmitError(''); setUploadError('')
      if (photoInputRef.current) photoInputRef.current.value = ''
      if (docInputRef.current)   docInputRef.current.value   = ''
      if (sopInputRef.current)   sopInputRef.current.value   = ''
    },
  }))

  const isDisabled = isLoading || disabled

  useEffect(() => {
    const apiUrl = import.meta.env.VITE_API_URL as string
    if (!apiUrl) return
    fetch(`${apiUrl}/proposals`)
      .then(r => r.json())
      .then((data: PastProposal[]) => setPastProposals(data))
      .catch(() => {})
  }, [])

  function handlePhotoFiles(files: File[]) {
    const invalid = files.filter(f => !isAllowedPhoto(f))
    if (invalid.length) { setPhotoError(`Only JPG/PNG allowed.`); return }
    setPhotoError(''); setPhotos(files)
  }

  function handleDocFiles(files: File[]) {
    const invalid = files.filter(f => !isAllowedDoc(f))
    if (invalid.length) { setDocError(`Only PDF/Word allowed.`); return }
    setDocError(''); setDocuments(files)
  }

  function handleSopFiles(files: File[]) {
    const invalid = files.filter(f => !isAllowedDoc(f))
    if (invalid.length) { setSopError(`Only PDF/Word allowed.`); return }
    setSopError(''); setSopDocs(files)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitError(''); setUploadError('')
    if (!surveyNotes.trim() && !photos.length && !documents.length && !sopDocs.length) {
      setSubmitError('Please enter survey notes or attach at least one file.')
      return
    }
    try {
      const photoKeys    = await Promise.all(photos.map(uploadFile))
      const documentKeys = await Promise.all(documents.map(uploadFile))
      const sopKeys      = await Promise.all(sopDocs.map(uploadFile))
      onSubmit({ surveyNotes, photoKeys, documentKeys, sopKeys, referenceProposalId: referenceProposalId || null })
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'File upload failed.')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3 pb-4 border-b border-gray-100">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: 'linear-gradient(135deg, #4F46E5, #06B6D4)' }}>
          <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
          </svg>
        </div>
        <div>
          <h2 className="text-base font-semibold text-gray-900">New Proposal</h2>
          <p className="text-xs text-gray-500">Fill in the details to generate an AI draft</p>
        </div>
      </div>

      {/* Survey Notes */}
      <div>
        <label htmlFor="survey-notes" className="block text-sm font-medium text-gray-700 mb-1.5">
          Survey Notes <span className="text-red-400">*</span>
        </label>
        <textarea
          id="survey-notes"
          value={surveyNotes}
          onChange={e => setSurveyNotes(e.target.value)}
          disabled={isDisabled}
          rows={6}
          placeholder="e.g. Site inspection completed on 12 April. Foundation requires reinforcement. Client requests 3-month timeline with budget under $50,000..."
          className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition-all disabled:bg-gray-50 disabled:cursor-not-allowed resize-none"
        />
      </div>

      {/* File uploads */}
      <DropZone
        id="photos" label="Site Photos" accept="image/jpeg,image/png" hint="JPG, PNG supported"
        files={photos} error={photoError} disabled={isDisabled} inputRef={photoInputRef}
        onFiles={handlePhotoFiles} onClear={() => { setPhotos([]); if (photoInputRef.current) photoInputRef.current.value = '' }}
      />
      <DropZone
        id="documents" label="Reference Documents" accept=".pdf,.doc,.docx" hint="PDF, Word supported"
        files={documents} error={docError} disabled={isDisabled} inputRef={docInputRef}
        onFiles={handleDocFiles} onClear={() => { setDocuments([]); if (docInputRef.current) docInputRef.current.value = '' }}
      />
      <DropZone
        id="sop-docs" label="SOP Documents" accept=".pdf,.doc,.docx" hint="PDF, Word supported"
        files={sopDocs} error={sopError} disabled={isDisabled} inputRef={sopInputRef}
        onFiles={handleSopFiles} onClear={() => { setSopDocs([]); if (sopInputRef.current) sopInputRef.current.value = '' }}
      />

      {/* Reference Proposal */}
      {pastProposals.length > 0 && (
        <div>
          <label htmlFor="reference-proposal" className="block text-sm font-medium text-gray-700 mb-1.5">
            Reference Past Proposal <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <select
            id="reference-proposal"
            value={referenceProposalId}
            onChange={e => setReferenceProposalId(e.target.value)}
            disabled={isDisabled}
            className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition-all disabled:bg-gray-50 disabled:cursor-not-allowed"
          >
            <option value="">— None —</option>
            {pastProposals.map(p => (
              <option key={p.proposalId} value={p.proposalId}>
                {p.proposalId.slice(0, 8)}... ({p.status})
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Errors */}
      {(submitError || uploadError) && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
          </svg>
          {submitError || uploadError}
        </div>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={isDisabled}
        className="w-full flex items-center justify-center gap-2 py-3 px-6 text-sm font-semibold text-white rounded-xl shadow-md transition-all duration-200 hover:opacity-90 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
        style={{ background: 'linear-gradient(135deg, #4F46E5, #06B6D4)' }}
      >
        {isLoading ? (
          <>
            <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
            Generating...
          </>
        ) : (
          <>
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Generate Draft
          </>
        )}
      </button>
    </form>
  )
})
