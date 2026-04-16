import { useState, useRef } from 'react'
import Navbar from '../components/Navbar'
import Sidebar from '../components/Sidebar'
import ProposalForm, { type GenerateRequest, type ProposalFormHandle } from '../components/ProposalForm'
import DraftOutput from '../components/DraftOutput'
interface Section {
  sectionName: string
  content: string
  rationale: string
}

interface DraftRecord {
  proposalId:          string
  status:              string
  aiGeneratedSections: Section[]
  rationale:           Record<string, string>
  createdAt:           string
  version:             number
}

const API_BASE = import.meta.env.VITE_API_URL as string

export default function Dashboard() {
  const [activeTab, setActiveTab]           = useState('new')
  const [sidebarOpen, setSidebarOpen]       = useState(false)
  const [draft, setDraft]                   = useState<DraftRecord | null>(null)
  const [error, setError]                   = useState<string | null>(null)
  const [isLoading, setIsLoading]           = useState(false)
  const [approveMessage, setApproveMessage] = useState<string | null>(null)
  const [pollStatus, setPollStatus]         = useState<string | null>(null)

  const submittingRef = useRef(false)
  const formRef       = useRef<ProposalFormHandle>(null)

  async function handleSubmit(formData: GenerateRequest) {
    if (submittingRef.current) return
    submittingRef.current = true
    setIsLoading(true)
    setError(null)
    setApproveMessage(null)
    setPollStatus(null)

    try {
      const res = await fetch(`${API_BASE}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError((body as { error?: string }).error ?? `Generation failed (HTTP ${res.status})`)
        return
      }

      const { proposalId } = (await res.json()) as { proposalId: string; status: string }
      setPollStatus('Generating proposal... this may take up to 60 seconds.')

      const maxAttempts = 40
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise(r => setTimeout(r, 3000))
        const pollRes = await fetch(`${API_BASE}/proposals/${proposalId}`)
        if (!pollRes.ok) continue
        const data = (await pollRes.json()) as DraftRecord

        if (data.status === 'PENDING') { setDraft(data); return }
        if (data.status === 'ERROR') {
          const errMsg = (data as unknown as { errorMessage?: string }).errorMessage ?? 'Generation failed'
          setError(errMsg.includes('503') || errMsg.includes('UNAVAILABLE')
            ? 'Gemini AI is currently overloaded. Please wait a moment and try again.'
            : errMsg)
          // Auto-clear error after 8 seconds
          setTimeout(() => setError(null), 8000)
          return
        }
      }
      setError('Generation timed out. Please try again.')
    } catch {
      setError('Network error — please check your connection and try again.')
    } finally {
      setIsLoading(false)
      setPollStatus(null)
      submittingRef.current = false
    }
  }

  async function handleApprove(sections: Section[]) {
    if (!draft) return
    try {
      const res = await fetch(`${API_BASE}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposalId: draft.proposalId, finalSections: sections, approvedBy: 'reviewer' }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError((body as { error?: string }).error ?? `Approval failed (HTTP ${res.status})`)
        return
      }
      setDraft(null)
      formRef.current?.reset()
      setApproveMessage('Proposal approved successfully.')
      setTimeout(() => setApproveMessage(null), 4000)
    } catch {
      setError('Network error during approval — please try again.')
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-[#F9FAFB]">
      <Navbar onMenuClick={() => setSidebarOpen(true)} />

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <Sidebar activeTab={activeTab} onTabChange={setActiveTab} isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

        {/* Main content */}
        <main className="flex-1 overflow-y-auto p-6">

          {/* Toast: polling */}
          {pollStatus && (
            <div className="fixed top-20 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-6 py-3.5 text-white rounded-2xl shadow-2xl text-sm font-medium" style={{ background: 'linear-gradient(135deg, #4F46E5, #06B6D4)' }}>
              <svg className="w-5 h-5 animate-spin shrink-0" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
              </svg>
              {pollStatus}
            </div>
          )}

          {/* Toast: success */}
          {approveMessage && (
            <div className="fixed top-20 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-6 py-3.5 text-white rounded-2xl shadow-2xl text-sm font-medium" style={{ background: 'linear-gradient(135deg, #10B981, #06B6D4)' }}>
              <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {approveMessage}
            </div>
          )}

          {/* Page title */}
          <div className="mb-6">
            <h1 className="text-2xl font-bold" style={{ color: '#111827' }}>
              {activeTab === 'settings' ? 'Settings' : activeTab === 'history' ? 'Proposal History' : 'New Proposal'}
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              {activeTab === 'settings'
                ? 'Manage your preferences.'
                : activeTab === 'history'
                ? 'View all past proposals.'
                : 'Generate an AI-powered proposal from your survey notes.'}
            </p>
          </div>

          {activeTab === 'new' && (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
              <ProposalForm ref={formRef} onSubmit={handleSubmit} isLoading={isLoading} disabled={false} />
              <DraftOutput draft={draft} error={error} onApprove={handleApprove} onRetry={() => setError(null)} />
            </div>
          )}

          {activeTab === 'history' && (
            <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-10 text-center text-gray-400">
              <svg className="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <p className="text-sm">Proposal history coming soon.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
